from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from retrofetch.events import EventBus, GameBytesEvent
from retrofetch.sources import DownloadCandidate, SourceUnavailable
from retrofetch.sources._cloudflare_base import (
    CloudflareBlocked,
    health,
    is_cloudflare_challenge,
    is_dead,
    make_scraper,
)

_log = logging.getLogger(__name__)

_SOURCE_NAME = "romsfun"
_BASE_URL = "https://romsfun.com/roms/"


class RomsfunSource:
    name = _SOURCE_NAME

    def __init__(self, console_entry: dict[str, Any], base_url: str = _BASE_URL):
        self.console_entry = console_entry
        self.slug = console_entry.get("romsfun_slug")
        self.extensions = tuple(console_entry.get("extensions") or [])
        self.base_url = base_url.rstrip("/") + "/"
        self._scraper: Any | None = None

    def _scraper_session(self) -> Any:
        if self._scraper is None:
            self._scraper = make_scraper()
        return self._scraper

    def _get(self, url: str) -> str:
        if is_dead(self.name):
            raise SourceUnavailable(f"{self.name} marked dead for session")
        scraper = self._scraper_session()
        try:
            resp = scraper.get(url, timeout=30)
        except Exception as exc:
            health(self.name).record_failure()
            raise SourceUnavailable(f"{self.name} request failed: {exc}") from exc
        if resp.status_code in (403, 503) or is_cloudflare_challenge(resp.text):
            health(self.name).record_failure()
            raise CloudflareBlocked(
                f"{self.name} Cloudflare challenge ({resp.status_code})"
            )
        if resp.status_code != 200:
            health(self.name).record_failure()
            raise SourceUnavailable(f"{self.name} HTTP {resp.status_code} for {url}")
        health(self.name).record_success()
        return resp.text

    def find_url_for_game(
        self,
        title: str,
        region_priority: list[str] | None = None,
    ) -> DownloadCandidate | None:
        if not self.slug:
            return None
        index_url = urljoin(self.base_url, f"{self.slug}/")
        try:
            body = self._get(index_url)
        except CloudflareBlocked as exc:
            _log.warning("%s cloudflare-blocked: %s", self.name, exc)
            return None
        except SourceUnavailable as exc:
            _log.warning("%s unavailable: %s", self.name, exc)
            return None
        slug_re = re.escape(self.slug)
        target_norm = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
        pattern = re.compile(
            rf"<a[^>]+href=\"([^\"]*/{slug_re}/[^\"]*{re.escape(target_norm)}[^\"]*)\"",
            re.IGNORECASE,
        )
        matches = pattern.findall(body)
        if not matches:
            return None
        game_url = urljoin(index_url, matches[0])
        try:
            game_body = self._get(game_url)
        except (CloudflareBlocked, SourceUnavailable):
            return None
        dl_match = re.search(
            r"href=\"([^\"]*download[^\"]*)\"[^>]*>[^<]*(?:Download|Get ROM)",
            game_body,
            re.IGNORECASE,
        )
        if not dl_match:
            return None
        download_url = urljoin(game_url, dl_match.group(1))
        default_ext = self.extensions[0] if self.extensions else ""
        filename = Path(download_url).name or f"{target_norm}{default_ext}"
        return DownloadCandidate(
            url=download_url,
            filename=filename,
            source=_SOURCE_NAME,
            extra={"game_page": game_url},
        )

    def list_popular(
        self, limit: int, region_priority: list[str] | None = None
    ) -> list[str]:
        if not self.slug:
            return []
        index_url = urljoin(self.base_url, f"{self.slug}/")
        body = self._get(index_url)
        slug_re = re.escape(str(self.slug))
        link_pattern = re.compile(
            rf"<a[^>]+href=\"([^\"]*/{slug_re}/([^\"/]+))\"[^>]*>([^<]+)</a>",
            re.IGNORECASE,
        )
        titles: list[str] = []
        seen: set[str] = set()
        for match in link_pattern.finditer(body):
            title = match.group(3).strip()
            if not title or title.lower() in seen:
                continue
            seen.add(title.lower())
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
        if is_dead(self.name):
            raise SourceUnavailable(f"{self.name} marked dead for session")
        scraper = self._scraper_session()
        dest_dir = Path(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)
        final = dest_dir / candidate.filename
        part = final.with_suffix(final.suffix + ".part")
        try:
            with scraper.get(candidate.url, stream=True, timeout=60) as resp:
                if resp.status_code != 200:
                    health(self.name).record_failure()
                    raise SourceUnavailable(
                        f"{self.name} download HTTP {resp.status_code}"
                    )
                total_raw = resp.headers.get("Content-Length")
                total = int(total_raw) if total_raw else None
                downloaded = 0
                with open(part, "wb") as fh:
                    for chunk in resp.iter_content(chunk_size=64 * 1024):
                        if not chunk:
                            continue
                        fh.write(chunk)
                        downloaded += len(chunk)
                        if event_bus is not None:
                            event_bus.publish(
                                GameBytesEvent(
                                    game=candidate.filename,
                                    downloaded=downloaded,
                                    total=total or downloaded,
                                )
                            )
        except SourceUnavailable:
            raise
        except Exception as exc:
            health(self.name).record_failure()
            raise SourceUnavailable(f"{self.name} download failed: {exc}") from exc
        part.replace(final)
        health(self.name).record_success()
        return final
