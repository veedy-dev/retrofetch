from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from retrofetch.catalog import CatalogEntry, CatalogFile, build_catalog
from retrofetch.config import Config
from retrofetch.downloader import stream_http_download
from retrofetch.events import EventBus
from retrofetch.sources import DownloadCandidate, SourceUnavailable

_log = logging.getLogger(__name__)

_SOURCE_NAME = "archive_org"
_ARTIFACT_SUFFIXES = (
    "_files.xml",
    "_meta.sqlite",
    "_meta.xml",
    "_reviews.xml",
    ".torrent",
    ".sqlite",
    ".xml",
    ".json",
    ".txt",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".pdf",
)
_MAX_METADATA_FILES = 20_000


class ArchiveOrgSource:
    name = _SOURCE_NAME

    def __init__(
        self,
        console_entry: dict[str, Any],
        *,
        metadata_base_url: str = "https://archive.org/metadata/",
        download_base_url: str = "https://archive.org/download/",
        timeout: float = 60.0,
    ):
        self.console_entry = console_entry
        self.identifier = console_entry.get("archive_org_identifier")
        self.extensions = tuple(console_entry.get("extensions") or [])
        self.exclude_keywords = list(
            console_entry.get("exclude_keywords")
            or Config(roms_root=Path("ROMs")).exclude_keywords
        )
        self.metadata_base_url = metadata_base_url.rstrip("/") + "/"
        self.download_base_url = download_base_url.rstrip("/") + "/"
        self.timeout = timeout
        self._catalog_cache: dict[tuple[str, ...], list[CatalogEntry]] = {}
        self._file_metadata: dict[str, dict[str, Any]] = {}

    @staticmethod
    def _internetarchive() -> Any:
        try:
            return importlib.import_module("internetarchive")
        except ImportError as exc:
            raise SourceUnavailable(
                f"internetarchive library not installed: {exc}"
            ) from exc

    @staticmethod
    def _coerce_size(value: Any) -> int | None:
        if value is None:
            return None
        try:
            return int(str(value))
        except ValueError:
            return None

    @staticmethod
    def _quote_identifier(identifier: str) -> str:
        return quote(identifier, safe="")

    @staticmethod
    def _quote_filename(filename: str) -> str:
        return "/".join(quote(part, safe="") for part in filename.split("/"))

    def _metadata_url(self) -> str | None:
        if not self.identifier:
            return None
        return self.metadata_base_url + self._quote_identifier(str(self.identifier))

    def _download_url(self, filename: str) -> str:
        identifier = str(self.identifier)
        return (
            self.download_base_url
            + self._quote_identifier(identifier)
            + "/"
            + self._quote_filename(filename)
        )

    def _fetch_metadata(self) -> dict[str, Any]:
        url = self._metadata_url()
        if url is None:
            return {}
        try:
            with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
                resp = client.get(url)
        except httpx.HTTPError as exc:
            raise SourceUnavailable(f"archive.org metadata unreachable: {exc}") from exc
        if resp.status_code == 404:
            return {}
        if resp.status_code != 200:
            raise SourceUnavailable(f"archive.org metadata HTTP {resp.status_code}")
        payload = resp.json()
        return payload if isinstance(payload, dict) else {}

    def _is_catalog_file(self, name: str) -> bool:
        name_lc = name.lower()
        if not name or name_lc.endswith(_ARTIFACT_SUFFIXES):
            return False
        if name_lc.startswith("__ia_thumb"):
            return False
        if self.extensions:
            return any(name_lc.endswith(ext.lower()) for ext in self.extensions)
        return "." in Path(name).name

    def _catalog_files(self) -> list[CatalogFile]:
        if not self.identifier:
            return []
        metadata = self._fetch_metadata()
        raw_files = metadata.get("files", [])
        if not isinstance(raw_files, list):
            return []
        files: list[CatalogFile] = []
        self._file_metadata = {}
        for raw in raw_files:
            if len(files) >= _MAX_METADATA_FILES:
                break
            if not isinstance(raw, dict):
                continue
            name = raw.get("name")
            if not isinstance(name, str) or not self._is_catalog_file(name):
                continue
            size = self._coerce_size(raw.get("size"))
            files.append(CatalogFile(name, self._download_url(name), size))
            self._file_metadata[name] = dict(raw)
        return files

    def _catalog_entries(
        self, region_priority: list[str] | None = None
    ) -> list[CatalogEntry]:
        priority = tuple(region_priority or Config(roms_root=Path("ROMs")).region_priority)
        cached = self._catalog_cache.get(priority)
        if cached is not None:
            return cached
        entries = build_catalog(
            self._catalog_files(),
            region_priority=list(priority),
            exclude_keywords=self.exclude_keywords,
        )
        for entry in entries:
            entry.source = _SOURCE_NAME
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
        self, title: str, region_priority: list[str] | None = None
    ) -> DownloadCandidate | None:
        entry = self.get_entry(title, region_priority)
        if entry is None or not entry.files:
            return None
        catalog_file = entry.files[0]
        metadata = self._file_metadata.get(catalog_file.filename, {})
        sha1 = metadata.get("sha1") or None
        crc32 = metadata.get("crc32") or None
        return DownloadCandidate(
            url=catalog_file.url,
            filename=catalog_file.filename,
            source=_SOURCE_NAME,
            expected_size=catalog_file.size,
            expected_sha1=str(sha1) if sha1 else None,
            expected_crc32=str(crc32) if crc32 else None,
            extra={
                "identifier": self.identifier,
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
        titles = [entry.title for entry in self._catalog_entries(region_priority)]
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
        identifier = (candidate.extra or {}).get("identifier", self.identifier)
        if not identifier:
            raise SourceUnavailable("archive.org candidate missing identifier")
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
            timeout=60.0,
            source_name=self.name,
            expected_size=candidate.expected_size,
        )
        return result.path
