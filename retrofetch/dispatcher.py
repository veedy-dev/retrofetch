from __future__ import annotations

import logging
from pathlib import Path
import threading
from typing import Any

from retrofetch.dat import GameEntry
from retrofetch.downloader import DownloadResult, Source, download_game, skip_if_acquired
from retrofetch.events import CloudflareBlockEvent, EventBus, SourceDeadEvent
from retrofetch.sources import DownloadCandidate, SourceUnavailable
from retrofetch.sources._cloudflare_base import is_dead as is_source_dead
from retrofetch.sources.archive_org import ArchiveOrgSource
from retrofetch.sources.minerva_http import MinervaHttpSource
from retrofetch.sources.minerva_torrent import MinervaTorrentSource
from retrofetch.sources.romsfun import RomsfunSource
from retrofetch.sources.romsretro import RomsretroSource
from retrofetch.state import State

_log = logging.getLogger(__name__)

_TORRENT_SOURCES = {"minerva_torrent"}

_SOURCE_FACTORIES: dict[str, Any] = {
    "archive_org": ArchiveOrgSource,
    "minerva_http": MinervaHttpSource,
    "minerva_torrent": MinervaTorrentSource,
    "romsfun": RomsfunSource,
    "romsretro": RomsretroSource,
}


class SourceDispatcher:
    def __init__(
        self,
        console_entry: dict[str, Any],
        source_names: list[str],
        allow_torrent: bool = True,
    ):
        self.console_entry = console_entry
        self.source_names = source_names
        self.allow_torrent = allow_torrent
        self._instances: dict[str, Source] = {}

    def _get_source(self, source_name: str) -> Source | None:
        if source_name in self._instances:
            return self._instances[source_name]
        factory = _SOURCE_FACTORIES.get(source_name)
        if factory is None:
            _log.warning("unknown source %s; skipping", source_name)
            return None
        if source_name == "minerva_torrent":
            instance = factory(self.console_entry, enabled=self.allow_torrent)
        else:
            instance = factory(self.console_entry)
        self._instances[source_name] = instance
        return instance

    def dispatch_download(
        self,
        game_title: str,
        game: GameEntry | None,
        target_dir: Path,
        region_priority: list[str],
        state: State,
        *,
        console: str,
        event_bus: EventBus | None = None,
        extract_archives: bool = False,
        verification_available: bool = True,
        state_lock: threading.Lock | None = None,
    ) -> DownloadResult:
        if state_lock is None:
            skipped = skip_if_acquired(
                state,
                game_title,
                target_dir,
                event_bus=event_bus,
            )
        else:
            with state_lock:
                skipped = skip_if_acquired(
                    state,
                    game_title,
                    target_dir,
                    event_bus=event_bus,
                )
        if skipped is not None:
            return skipped
        attempts_summary: list[str] = []
        published_dead_sources: set[str] = set()
        for source_name in self.source_names:
            if not self.allow_torrent and source_name in _TORRENT_SOURCES:
                attempts_summary.append(f"{source_name}:skipped_no_torrent")
                continue
            if is_source_dead(source_name):
                attempts_summary.append(f"{source_name}:dead")
                if event_bus is not None and source_name not in published_dead_sources:
                    event_bus.publish(
                        SourceDeadEvent(
                            source=source_name,
                            reason="marked dead for session",
                        )
                    )
                    published_dead_sources.add(source_name)
                continue
            source = self._get_source(source_name)
            if source is None:
                continue
            try:
                candidate: DownloadCandidate | None = source.find_url_for_game(
                    game_title, region_priority
                )
            except SourceUnavailable as exc:
                _log.info("%s find failed for %s: %s", source_name, game_title, exc)
                attempts_summary.append(f"{source_name}:find_failed")
                continue
            if candidate is None:
                attempts_summary.append(f"{source_name}:no_match")
                continue
            result = download_game(
                source=source,
                candidate=candidate,
                target_dir=target_dir,
                game=game,
                game_title=game_title,
                state=state,
                console=console,
                event_bus=event_bus,
                extract_archives=extract_archives,
                verification_available=verification_available,
                state_lock=state_lock,
            )
            if event_bus is not None and result.reason:
                if "cloudflare" in result.reason.lower():
                    event_bus.publish(
                        CloudflareBlockEvent(source=source_name, status=0)
                    )
            if result.status in ("acquired", "skipped", "unverified"):
                result.reason = ";".join(attempts_summary + [f"{source_name}:{result.status}"])
                return result
            attempts_summary.append(f"{source_name}:{result.status}")
        return DownloadResult(
            status="failed",
            reason="; ".join(attempts_summary) or "no sources attempted",
        )
