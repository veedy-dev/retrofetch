from __future__ import annotations

import importlib
import logging
import posixpath
import re
import threading
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urljoin, urlsplit, urlunsplit

import httpx

from retrofetch.catalog import CatalogEntry, CatalogFile, build_catalog
from retrofetch.config import Config
from retrofetch.downloader import stream_http_download
from retrofetch.events import EventBus
from retrofetch.sources import DownloadCandidate, SourceUnavailable

_log = logging.getLogger(__name__)

_SOURCE_NAME = "minerva_http"
_BASE_URL = "https://minerva-archive.org/browse/"
_MAX_CATALOG_FILES = 20_000
_MAX_CATALOG_PAGES = 200
_SIZE_RE = re.compile(
    r"(?P<num>\d+(?:\.\d+)?)\s*(?P<unit>B|KiB|MiB|GiB|KB|MB|GB)",
    re.IGNORECASE,
)
_FALLBACK_FILE_SUFFIXES = (
    ".7z",
    ".zip",
    ".rar",
    ".iso",
    ".chd",
    ".rvz",
    ".wbfs",
    ".bin",
    ".cue",
    ".nes",
    ".sfc",
    ".smc",
    ".gb",
    ".gbc",
    ".gba",
    ".vb",
)


class _DirectoryEntry:
    def __init__(self, name: str, url: str, *, size: int | None, is_dir: bool) -> None:
        self.name = name
        self.url = url
        self.size = size
        self.is_dir = is_dir


class MinervaHttpSource:
    name = _SOURCE_NAME

    def __init__(
        self,
        console_entry: dict[str, Any],
        base_url: str = _BASE_URL,
        timeout: float = 30.0,
    ):
        self.console_entry = console_entry
        self.minerva_path = console_entry.get("minerva_path")
        self.extensions = tuple(console_entry.get("extensions") or [])
        self.base_url = base_url.rstrip("/") + "/"
        self.timeout = timeout
        self.exclude_keywords = list(
            console_entry.get("exclude_keywords")
            or Config(roms_root=Path("ROMs")).exclude_keywords
        )
        self._catalog_cache: dict[tuple[str, ...], list[CatalogEntry]] = {}
        self._catalog_lock = threading.Lock()

    @staticmethod
    def _html_parser(body: str) -> Any:
        try:
            parser_mod = importlib.import_module("selectolax.parser")
        except ImportError as exc:
            raise SourceUnavailable(f"selectolax not installed: {exc}") from exc
        return parser_mod.HTMLParser(body)

    def _build_index_url(self) -> str | None:
        if not self.minerva_path:
            return None
        path = str(self.minerva_path).strip("/")
        return urljoin(self.base_url, path + "/")

    def _fetch_text(self, url: str) -> str:
        try:
            with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
                resp = client.get(url)
        except httpx.HTTPError as exc:
            raise SourceUnavailable(f"minerva index unreachable: {exc}") from exc
        if resp.status_code == 404:
            raise SourceUnavailable(f"minerva index not found: {url}")
        if resp.status_code >= 500:
            raise SourceUnavailable(f"minerva server error {resp.status_code}")
        if resp.status_code != 200:
            raise SourceUnavailable(f"minerva unexpected status {resp.status_code}")
        return resp.text

    @staticmethod
    def _quote_url(url: str) -> str:
        parts = urlsplit(url)
        return urlunsplit(
            (
                parts.scheme,
                parts.netloc,
                quote(parts.path, safe="/:%"),
                quote(parts.query, safe="=&/%:+"),
                parts.fragment,
            )
        )

    @staticmethod
    def _node_text(node: Any) -> str:
        try:
            return str(node.text(separator=" ", strip=True))
        except TypeError:
            return str(node.text()).strip()
        except Exception:
            return ""

    @classmethod
    def _parse_size(cls, text: str) -> int | None:
        matches = list(_SIZE_RE.finditer(text))
        if not matches:
            return None
        match = matches[-1]
        value = float(match.group("num"))
        unit = match.group("unit").lower()
        multipliers = {
            "b": 1,
            "kb": 1_000,
            "mb": 1_000_000,
            "gb": 1_000_000_000,
            "kib": 1024,
            "mib": 1024**2,
            "gib": 1024**3,
        }
        return int(value * multipliers[unit])

    @classmethod
    def _context_text(cls, link: Any) -> str:
        parent = getattr(link, "parent", None)
        if parent is not None:
            try:
                span = parent.css_first("span")
            except Exception:
                span = None
            if span is not None:
                return cls._node_text(span)
            grandparent = getattr(parent, "parent", None)
            if grandparent is not None and str(getattr(grandparent, "tag", "")).lower() in {"tr", "li"}:
                return cls._node_text(grandparent)
        return cls._node_text(link)

    @staticmethod
    def _filename_from_link(href: str, label: str) -> str:
        parts = urlsplit(href)
        if parts.path.rstrip("/") == "/rom":
            values = parse_qs(parts.query).get("name") or []
            if values:
                return unquote(posixpath.basename(values[0].rstrip("/")))
        basename = posixpath.basename(parts.path.rstrip("/"))
        if basename:
            return unquote(basename)
        return unquote(label.strip())

    def _is_supported_file(self, name: str) -> bool:
        name_lc = name.lower()
        if self.extensions:
            return any(name_lc.endswith(ext.lower()) for ext in self.extensions)
        return any(name_lc.endswith(ext) for ext in _FALLBACK_FILE_SUFFIXES)

    def _list_directory(self, url: str) -> list[_DirectoryEntry]:
        body = self._fetch_text(url)
        parser = self._html_parser(body)
        entries: list[_DirectoryEntry] = []
        for link in parser.css("a"):
            href = link.attributes.get("href")
            if not href or href.startswith("?") or href in ("../", "/"):
                continue
            label = self._node_text(link)
            name = self._filename_from_link(href, label)
            if not name or name in {".", ".."}:
                continue
            is_rom_link = urlsplit(href).path.rstrip("/") == "/rom"
            is_dir = href.endswith("/") and not is_rom_link
            absolute = self._quote_url(urljoin(url, href))
            if is_dir:
                current_path = urlsplit(url).path.rstrip("/") + "/"
                entry_path = urlsplit(absolute).path.rstrip("/") + "/"
                if entry_path == current_path or not entry_path.startswith(current_path):
                    continue
            size = None if is_dir else self._parse_size(self._context_text(link))
            entries.append(_DirectoryEntry(name, absolute, size=size, is_dir=is_dir))
        return entries

    def _list_catalog_files(self, root_url: str) -> list[CatalogFile]:
        files: list[CatalogFile] = []
        seen_files: set[tuple[str, str]] = set()
        pages_seen = 0
        visited: set[str] = set()

        def visit(url: str, depth: int) -> None:
            nonlocal pages_seen
            if url in visited or pages_seen >= _MAX_CATALOG_PAGES:
                return
            visited.add(url)
            pages_seen += 1
            for entry in self._list_directory(url):
                if len(files) >= _MAX_CATALOG_FILES:
                    return
                if entry.is_dir:
                    if depth < 1:
                        visit(entry.url, depth + 1)
                    continue
                if not self._is_supported_file(entry.name):
                    continue
                key = (entry.name.casefold(), entry.url)
                if key in seen_files:
                    continue
                seen_files.add(key)
                files.append(CatalogFile(entry.name, entry.url, entry.size))

        visit(root_url, 0)
        return files

    def _catalog_entries(
        self, region_priority: list[str] | None = None
    ) -> list[CatalogEntry]:
        priority = tuple(region_priority or Config(roms_root=Path("ROMs")).region_priority)
        with self._catalog_lock:
            cached = self._catalog_cache.get(priority)
            if cached is not None:
                return cached
        url = self._build_index_url()
        if not url:
            return []
        files = self._list_catalog_files(url)
        entries = build_catalog(
            files,
            region_priority=list(priority),
            exclude_keywords=self.exclude_keywords,
        )
        for entry in entries:
            entry.source = _SOURCE_NAME
        with self._catalog_lock:
            self._catalog_cache[priority] = entries
        return entries

    def get_entry(
        self, title: str, region_priority: list[str] | None = None
    ) -> CatalogEntry | None:
        title_lc = title.casefold()
        for entry in self._catalog_entries(region_priority):
            if entry.title.casefold() == title_lc:
                return entry
        return None

    def find_url_for_game(
        self,
        title: str,
        region_priority: list[str] | None = None,
    ) -> DownloadCandidate | None:
        entry = self.get_entry(title, region_priority)
        if entry is None or not entry.files:
            return None
        catalog_file = entry.files[0]
        return DownloadCandidate(
            url=catalog_file.url,
            filename=catalog_file.filename,
            source=_SOURCE_NAME,
            expected_size=catalog_file.size,
            extra={
                "minerva_path": self.minerva_path,
                "catalog_title": entry.title,
                "catalog_region": entry.region,
                "catalog_files": [
                    {"filename": file.filename, "url": file.url, "size": file.size}
                    for file in entry.files
                ],
            },
        )

    @staticmethod
    def _region_rank(name: str, region_priority: list[str]) -> int:
        name_lc = name.lower()
        for i, region in enumerate(region_priority):
            if region.lower() in name_lc:
                return i
        return len(region_priority) + 1

    def list_popular(
        self, limit: int, region_priority: list[str] | None = None
    ) -> list[str]:
        entries = self._catalog_entries(region_priority)
        titles = [entry.title for entry in entries]
        if limit is None or limit <= 0:
            return titles
        return titles[:limit]

    def download(
        self,
        candidate: DownloadCandidate,
        dest_dir: Path,
        *,
        event_bus: EventBus | None = None,
    ) -> Path:
        dest_dir = Path(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)
        catalog_files = (candidate.extra or {}).get("catalog_files")
        if isinstance(catalog_files, list) and catalog_files:
            first_path: Path | None = None
            seen: set[str] = set()
            for raw_file in catalog_files:
                if not isinstance(raw_file, dict):
                    continue
                url = raw_file.get("url")
                filename = raw_file.get("filename")
                size = raw_file.get("size")
                if not isinstance(url, str) or not isinstance(filename, str):
                    continue
                if filename in seen:
                    continue
                seen.add(filename)
                result = stream_http_download(
                    url,
                    dest_dir / filename,
                    event_bus=event_bus,
                    event_game=filename,
                    timeout=self.timeout,
                    source_name=self.name,
                    expected_size=size if isinstance(size, int) else None,
                )
                if first_path is None:
                    first_path = result.path
            if first_path is not None:
                return first_path

        final = dest_dir / candidate.filename
        result = stream_http_download(
            candidate.url,
            final,
            event_bus=event_bus,
            event_game=candidate.filename,
            timeout=self.timeout,
            source_name=self.name,
            expected_size=candidate.expected_size,
        )
        return result.path
