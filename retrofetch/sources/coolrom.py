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

_SOURCE_NAME = "coolrom"
_BASE_URL = "https://coolrom.com.au"


class CoolROMSource:
    """Catalog-only adapter.

    CoolROM can intermittently return Cloudflare challenge pages. When that
    happens, list_popular records a failure and returns an empty result so the
    ranker can keep falling back.
    """

    name = _SOURCE_NAME

    def __init__(self, console_entry: dict[str, Any]):
        self.console_entry = console_entry
        self.slug = console_entry.get("coolrom_slug")
        self.extensions = tuple(console_entry.get("extensions") or [])
        self._scraper: Any | None = None

    def _scraper_session(self) -> Any:
        if self._scraper is None:
            self._scraper = make_scraper()
        return self._scraper

    def _get(self, path: str, *, allow_missing: bool = False) -> str | None:
        if is_dead(self.name):
            return None
        url = f"{_BASE_URL}{path}"
        try:
            resp = self._scraper_session().get(url, timeout=30, allow_redirects=False)
        except Exception as exc:
            health(self.name).record_failure()
            raise SourceUnavailable(f"{self.name} request failed: {exc}") from exc
        if resp.status_code in (301, 302, 303, 307, 308):
            location = resp.headers.get("Location", "")
            if allow_missing and ("removed.php" in location or location):
                return None
            health(self.name).record_failure()
            raise SourceUnavailable(f"{self.name} redirect for {url}: {location}")
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
        slug = re.escape(str(self.slug or ""))
        section_match = re.search(
            r'Top 25 .*? ROMs</b></font></center><br>(.*?)(?:</font>\s*</td></tr></table>|<br>\s*</font>\s*</td></tr></table>)',
            body,
            re.IGNORECASE | re.DOTALL,
        )
        section = section_match.group(1) if section_match else body
        title_pattern = re.compile(
            rf'<a href="/roms/{slug}/\d+/[^"]+"[^>]*title="([^"]+)"',
            re.IGNORECASE,
        )
        titles: list[str] = []
        seen: set[str] = set()
        for raw_title in title_pattern.findall(section):
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
            body = self._get(f"/roms/{self.slug}/", allow_missing=True)
        except CloudflareBlocked as exc:
            _log.warning("%s cloudflare-blocked: %s", self.name, exc)
            return []
        if body is None:
            return []
        return self._extract_titles(body)[:limit]

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
        raise SourceUnavailable(
            "coolrom download not implemented in catalog-only adapter"
        )
