from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urljoin

import httpx

from retrofetch.downloader import stream_http_download
from retrofetch.events import EventBus
from retrofetch.sources import DownloadCandidate, SourceUnavailable

_log = logging.getLogger(__name__)

_SOURCE_NAME = "minerva_http"
_BASE_URL = "https://minerva-archive.org/browse/"


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

    def _list_directory(self, url: str) -> list[tuple[str, str]]:
        try:
            with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
                resp = client.get(url)
        except httpx.HTTPError as exc:
            raise SourceUnavailable(f"minerva index unreachable: {exc}") from exc
        if resp.status_code == 404:
            return []
        if resp.status_code >= 500:
            raise SourceUnavailable(f"minerva server error {resp.status_code}")
        if resp.status_code != 200:
            raise SourceUnavailable(f"minerva unexpected status {resp.status_code}")
        parser = self._html_parser(resp.text)
        entries: list[tuple[str, str]] = []
        for link in parser.css("a"):
            href = link.attributes.get("href")
            if not href or href.startswith("?") or href in ("../", "/"):
                continue
            name = unquote(href.rstrip("/"))
            entries.append((name, urljoin(url, href)))
        return entries

    def find_url_for_game(
        self,
        title: str,
        region_priority: list[str] | None = None,
    ) -> DownloadCandidate | None:
        url = self._build_index_url()
        if not url:
            return None
        entries = self._list_directory(url)
        target_lc = title.lower()
        matches: list[tuple[str, str]] = []
        for name, href in entries:
            name_lc = name.lower()
            if self.extensions and not any(
                name_lc.endswith(ext.lower()) for ext in self.extensions
            ):
                continue
            if target_lc not in name_lc:
                continue
            matches.append((name, href))
        if not matches:
            return None
        if region_priority:
            matches.sort(key=lambda nh: self._region_rank(nh[0], region_priority))
        name, href = matches[0]
        return DownloadCandidate(
            url=href,
            filename=name,
            source=_SOURCE_NAME,
            extra={"minerva_path": self.minerva_path},
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
        return []

    def download(
        self,
        candidate: DownloadCandidate,
        dest_dir: Path,
        *,
        event_bus: EventBus | None = None,
    ) -> Path:
        dest_dir = Path(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)
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
