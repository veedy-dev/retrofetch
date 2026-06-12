from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import Any

from retrofetch.downloader import stream_http_download
from retrofetch.events import EventBus
from retrofetch.sources import DownloadCandidate, SourceUnavailable

_log = logging.getLogger(__name__)

_SOURCE_NAME = "archive_org"


class ArchiveOrgSource:
    name = _SOURCE_NAME

    def __init__(self, console_entry: dict[str, Any]):
        self.console_entry = console_entry
        self.identifier = console_entry.get("archive_org_identifier")
        self.extensions = tuple(console_entry.get("extensions") or [])

    @staticmethod
    def _internetarchive() -> Any:
        try:
            return importlib.import_module("internetarchive")
        except ImportError as exc:
            raise SourceUnavailable(
                f"internetarchive library not installed: {exc}"
            ) from exc

    def find_url_for_game(
        self, title: str, region_priority: list[str] | None = None
    ) -> DownloadCandidate | None:
        ia = self._internetarchive()
        if not self.identifier:
            return None
        try:
            item = ia.get_item(self.identifier)
        except Exception as exc:
            raise SourceUnavailable(
                f"archive.org item unreachable: {self.identifier}: {exc}"
            ) from exc
        files = getattr(item, "files", None) or []
        target_lc = title.lower()
        best: dict[str, Any] | None = None
        for f in files:
            name = f.get("name", "")
            name_lc = name.lower()
            if self.extensions and not any(
                name_lc.endswith(ext.lower()) for ext in self.extensions
            ):
                continue
            if target_lc not in name_lc:
                continue
            if best is None:
                best = f
                continue
            if region_priority:
                cur_rank = self._region_rank(name, region_priority)
                best_rank = self._region_rank(best.get("name", ""), region_priority)
                if cur_rank < best_rank:
                    best = f
        if best is None:
            return None
        filename = best.get("name", "")
        size_raw = best.get("size")
        size = int(size_raw) if size_raw and str(size_raw).isdigit() else None
        sha1 = best.get("sha1") or None
        crc32 = best.get("crc32") or None
        url = f"https://archive.org/download/{self.identifier}/{filename}"
        return DownloadCandidate(
            url=url,
            filename=filename,
            source=_SOURCE_NAME,
            expected_size=size,
            expected_sha1=sha1,
            expected_crc32=crc32,
            extra={"identifier": self.identifier},
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
        if not self.identifier:
            return []
        try:
            search = self._internetarchive().search_items(
                f"collection:{self.identifier}",
                fields=["title"],
                sorts=["downloads desc"],
                params={"rows": max(limit * 2, 50)},
            )
        except Exception as exc:
            raise SourceUnavailable(
                f"archive.org search failed for {self.identifier}: {exc}"
            ) from exc

        titles: list[str] = []
        for item in search:
            title = item.get("title") if isinstance(item, dict) else None
            if title and title not in titles:
                titles.append(title)
            if len(titles) >= limit:
                break
        return titles

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
