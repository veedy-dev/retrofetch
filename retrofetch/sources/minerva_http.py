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

logger = logging.getLogger(__name__)

_SOURCE_NAME = "minerva_http"
_BASE_URL = "https://minerva-archive.org/browse/"
_MAX_CATALOG_FILES = 20_000
_MAX_CATALOG_PAGES = 200
_SIZE_RE = re.compile(
    r"(?P<num>\d+(?:\.\d+)?)\s*(?P<unit>B|KiB|MiB|GiB|KB|MB|GB)",
    re.IGNORECASE,
)
_ARCHIVE_SUFFIXES = (".zip", ".7z", ".rar")
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


def effective_minerva_paths(console_entry: dict[str, Any]) -> list[str]:
    primary = console_entry.get("minerva_path")
    if not isinstance(primary, str):
        return []
    primary = primary.strip().strip("/")
    if not primary:
        return []
    roots = [primary]

    supplements = console_entry.get("minerva_paths")
    if not isinstance(supplements, list):
        return roots
    for value in supplements:
        if not isinstance(value, str):
            continue
        root = value.strip().strip("/")
        if root and root not in roots:
            roots.append(root)
    return roots


class MinervaHttpSource:
    name = _SOURCE_NAME

    def __init__(
        self,
        console_entry: dict[str, Any],
        base_url: str = _BASE_URL,
        timeout: float = 30.0,
    ):
        self.console_entry = console_entry
        self.minerva_paths = effective_minerva_paths(console_entry)
        self.minerva_path = self.minerva_paths[0] if self.minerva_paths else None
        self.extensions = tuple(console_entry.get("extensions") or [])
        self.base_url = base_url.rstrip("/") + "/"
        self.timeout = timeout
        self.exclude_keywords = list(
            console_entry.get("exclude_keywords")
            or Config(roms_root=Path("ROMs")).exclude_keywords
        )
        self._catalog_cache: dict[tuple[str, ...], list[tuple[str, CatalogEntry]]] = {}
        self._catalog_lock = threading.Lock()

    @staticmethod
    def _html_parser(body: str) -> Any:
        try:
            parser_mod = importlib.import_module("selectolax.parser")
        except ImportError as exc:
            raise SourceUnavailable(f"selectolax not installed: {exc}") from exc
        return parser_mod.HTMLParser(body)

    def _build_index_url(self, minerva_path: str | None = None) -> str | None:
        selected_path = self.minerva_path if minerva_path is None else minerva_path
        if not selected_path:
            return None
        path = str(selected_path).strip("/")
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
        except Exception as exc:
            # Parser errors may contain source content; log only their type.
            logger.exception(
                "minerva node text unavailable: %s", type(exc).__name__, exc_info=False
            )
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
            except Exception as exc:
                # Avoid exposing source content through exception text or chains.
                logger.exception(
                    "minerva size context unavailable: %s", type(exc).__name__, exc_info=False
                )
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
            return unquote(label.strip())
        basename = posixpath.basename(parts.path.rstrip("/"))
        if basename:
            return unquote(basename)
        return unquote(label.strip())

    def _is_supported_file(self, name: str) -> bool:
        name_lc = name.lower()
        if name_lc.endswith(_ARCHIVE_SUFFIXES):
            return True
        if self.extensions:
            return any(
                name_lc.endswith("." + ext.lower().lstrip(".")) for ext in self.extensions
            )
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
            if is_rom_link and not parse_qs(urlsplit(href).query).get("name"):
                browse_path = (
                    unquote(urlsplit(url).path).partition("/browse/")[2].lstrip("./")
                )
                if browse_path:
                    separator = "&" if "?" in href else "?"
                    full_path = quote(posixpath.join(browse_path, name), safe="/")
                    href = f"{href}{separator}name={full_path}"
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

    def _catalog_entries_with_roots(
        self, region_priority: list[str] | None = None
    ) -> list[tuple[str, CatalogEntry]]:
        priority = tuple(region_priority or Config(roms_root=Path("ROMs")).region_priority)
        with self._catalog_lock:
            cached = self._catalog_cache.get(priority)
            if cached is not None:
                return cached

        if not self.minerva_paths:
            return []

        merged: list[tuple[str, CatalogEntry]] = []
        seen_titles: set[str] = set()
        failures: list[SourceUnavailable] = []
        successful_roots = 0
        for index, root in enumerate(self.minerva_paths):
            url = self._build_index_url(root)
            assert url is not None
            try:
                files = self._list_catalog_files(url)
            except SourceUnavailable as exc:
                failures.append(exc)
                logger.warning("minerva collection unavailable (%s): %s", root, exc)
                continue

            successful_roots += 1
            entries = build_catalog(
                files,
                region_priority=list(priority),
                exclude_keywords=self.exclude_keywords,
            )
            for entry in entries:
                if index > 0 and len(entry.files) != 1:
                    continue
                key = entry.title.casefold()
                if key in seen_titles:
                    continue
                seen_titles.add(key)
                entry.source = _SOURCE_NAME
                merged.append((root, entry))

        if successful_roots == 0 and failures:
            raise failures[0]
        with self._catalog_lock:
            self._catalog_cache[priority] = merged
        return merged

    def _catalog_entries(
        self, region_priority: list[str] | None = None
    ) -> list[CatalogEntry]:
        return [
            entry for _root, entry in self._catalog_entries_with_roots(region_priority)
        ]

    def get_entry(
        self, title: str, region_priority: list[str] | None = None
    ) -> CatalogEntry | None:
        resolved = self.get_entry_with_root(title, region_priority)
        return resolved[1] if resolved is not None else None

    def get_entry_with_root(
        self, title: str, region_priority: list[str] | None = None
    ) -> tuple[str, CatalogEntry] | None:
        title_lc = title.casefold()
        for root, entry in self._catalog_entries_with_roots(region_priority):
            if entry.title.casefold() == title_lc:
                return root, entry
        return None

    def find_url_for_game(
        self,
        title: str,
        region_priority: list[str] | None = None,
    ) -> DownloadCandidate | None:
        resolved = self.get_entry_with_root(title, region_priority)
        if resolved is None:
            return None
        root, entry = resolved
        if not entry.files:
            return None
        catalog_file = entry.files[0]
        # MiNERVA's /rom endpoint is an information page; its documented
        # payload delivery is torrent-only, so it is browse metadata, not HTTP.
        if urlsplit(catalog_file.url).path.rstrip("/") == "/rom":
            return None
        return DownloadCandidate(
            url=catalog_file.url,
            filename=catalog_file.filename,
            source=_SOURCE_NAME,
            expected_size=catalog_file.size,
            extra={
                "minerva_path": root,
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
