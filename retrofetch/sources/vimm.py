from __future__ import annotations

import html
import logging
import re
from pathlib import Path
from typing import Any

from retrofetch.events import EventBus
from retrofetch.sources import DownloadCandidate, SourceUnavailable
from retrofetch.sources._cloudflare_base import (
    CloudflareBlocked,
    health,
    is_cloudflare_challenge,
    is_dead,
    make_scraper,
)

_log = logging.getLogger(__name__)

_SOURCE_NAME = "vimm"
_BASE_URL = "https://vimm.net"
_TITLE_RE = re.compile(r"<a[^>]+href=\"[^\"]+\"[^>]*>([^<]+)</a>", re.IGNORECASE)


class VimmSource:
    name = _SOURCE_NAME

    def __init__(self, console_entry: dict[str, Any]):
        self.console_entry = console_entry
        self.slug = console_entry.get("vimm_slug")
        self.extensions = tuple(console_entry.get("extensions") or [])
        self._scraper: Any | None = None

    def _scraper_session(self) -> Any:
        if self._scraper is None:
            self._scraper = make_scraper()
        return self._scraper

    def _get(self, path: str, *, allow_missing: bool = False) -> str | None:
        if is_dead(self.name):
            raise SourceUnavailable(f"{self.name} marked dead for session")
        url = f"{_BASE_URL}{path}"
        try:
            resp = self._scraper_session().get(url, timeout=30)
        except Exception as exc:
            health(self.name).record_failure()
            raise SourceUnavailable(f"{self.name} request failed: {exc}") from exc
        if resp.status_code in (403, 503) or is_cloudflare_challenge(resp.text):
            health(self.name).record_failure()
            raise CloudflareBlocked(f"{self.name} challenge ({resp.status_code})")
        if resp.status_code == 404 and allow_missing:
            return None
        if resp.status_code != 200:
            health(self.name).record_failure()
            raise SourceUnavailable(f"{self.name} HTTP {resp.status_code} for {url}")
        health(self.name).record_success()
        return resp.text

    def _extract_titles(self, body: str) -> list[str]:
        section = body
        section_match = re.search(
            r'id="topTen"[^>]*>(.*?)</tbody></table>',
            body,
            re.IGNORECASE | re.DOTALL,
        )
        if section_match:
            section = section_match.group(1)
        titles: list[str] = []
        seen: set[str] = set()
        for raw_title in _TITLE_RE.findall(section):
            title = html.unescape(raw_title).strip()
            key = title.lower()
            if not title or key in seen:
                continue
            seen.add(key)
            titles.append(title)
        return titles

    def list_popular(
        self, limit: int, region_priority: list[str] | None = None
    ) -> list[str]:
        if not self.slug or limit <= 0:
            return []
        try:
            body = self._get(f"/vault/{self.slug}", allow_missing=True)
        except CloudflareBlocked as exc:
            raise SourceUnavailable(str(exc)) from exc
        if body is None:
            return []

        titles = self._extract_titles(body)
        if len(titles) >= limit:
            return titles[:limit]

        seen = {title.lower() for title in titles}
        page = 2
        while len(titles) < limit:
            try:
                extra = self._get(
                    f"/vault/ajax/loadTopTen.php?system={self.slug}&page={page}",
                    allow_missing=True,
                )
            except CloudflareBlocked as exc:
                _log.warning("%s pagination blocked: %s", self.name, exc)
                break
            if not extra:
                break
            page_titles = self._extract_titles(extra)
            if not page_titles:
                break
            added = 0
            for title in page_titles:
                key = title.lower()
                if key in seen:
                    continue
                seen.add(key)
                titles.append(title)
                added += 1
                if len(titles) >= limit:
                    return titles[:limit]
            if added == 0:
                break
            page += 1
        return titles[:limit]

    def find_url_for_game(
        self, title: str, region_priority: list[str] | None = None
    ) -> DownloadCandidate | None:
        return None

    def download(
        self,
        candidate: DownloadCandidate,
        dest_dir: Path,
        *,
        event_bus: EventBus | None = None,
    ) -> Path:
        raise SourceUnavailable("vimm download not implemented in catalog-only adapter")
