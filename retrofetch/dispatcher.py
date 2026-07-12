from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path
import threading
from typing import Any

from retrofetch.dat import GameEntry
from retrofetch.downloader import DownloadResult, Source, download_game, skip_if_acquired
from retrofetch.events import (
    CloudflareBlockEvent,
    EventBus,
    GameFailedEvent,
    GameStartEvent,
    SourceDeadEvent,
)
from retrofetch.sources import DownloadCandidate, SourceUnavailable
from retrofetch.sources._cloudflare_base import is_dead as is_source_dead
from retrofetch.sources.archive_org import ArchiveOrgSource
from retrofetch.sources.minerva_http import MinervaHttpSource
from retrofetch.sources.minerva_torrent import MinervaTorrentSource
from retrofetch.sources.romsfun import RomsfunSource
from retrofetch.sources.romsretro import RomsretroSource
from retrofetch.state import State
from retrofetch.torrent import (
    PreparedTorrent,
    TorrentCoordinator,
    TorrentTransferSource,
)

_log = logging.getLogger(__name__)

_TORRENT_SOURCES = {"minerva_torrent"}

_SOURCE_FACTORIES: dict[str, Any] = {
    "archive_org": ArchiveOrgSource,
    "minerva_http": MinervaHttpSource,
    "minerva_torrent": MinervaTorrentSource,
    "romsfun": RomsfunSource,
    "romsretro": RomsretroSource,
}


@dataclass(frozen=True)
class DeferredTorrentAttempt:
    source_index: int
    source_name: str
    candidate: DownloadCandidate
    attempts_summary: tuple[str, ...]
    item_id: str


class SourceDispatcher:
    def __init__(
        self,
        console_entry: dict[str, Any],
        source_names: list[str],
        allow_torrent: bool = True,
        torrent_coordinator: TorrentCoordinator | None = None,
    ):
        self.console_entry = console_entry
        self.source_names = source_names
        self.allow_torrent = allow_torrent
        self.torrent_coordinator = torrent_coordinator
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
        result = self._dispatch_download(
            game_title,
            game,
            target_dir,
            region_priority,
            state,
            console=console,
            event_bus=event_bus,
            extract_archives=extract_archives,
            verification_available=verification_available,
            state_lock=state_lock,
            defer_torrent=False,
        )
        assert isinstance(result, DownloadResult)
        return result

    def dispatch_until_torrent(
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
    ) -> DownloadResult | DeferredTorrentAttempt:
        return self._dispatch_download(
            game_title,
            game,
            target_dir,
            region_priority,
            state,
            console=console,
            event_bus=event_bus,
            extract_archives=extract_archives,
            verification_available=verification_available,
            state_lock=state_lock,
            defer_torrent=True,
        )

    def resume_download(
        self,
        deferred: DeferredTorrentAttempt,
        *,
        prepared: PreparedTorrent | None,
        transfer_error: Exception | None,
        game_title: str,
        game: GameEntry | None,
        target_dir: Path,
        region_priority: list[str],
        state: State,
        console: str,
        event_bus: EventBus | None = None,
        extract_archives: bool = False,
        verification_available: bool = True,
        state_lock: threading.Lock | None = None,
    ) -> DownloadResult:
        if self.torrent_coordinator is None:
            raise RuntimeError("torrent coordinator is unavailable")
        source = TorrentTransferSource(
            self.torrent_coordinator,
            source_name=deferred.source_name,
            game_title=game_title,
            item_id=deferred.item_id,
            state=state,
            state_lock=state_lock,
            prepared=prepared,
            transfer_error=transfer_error,
        )
        result = download_game(
            source=source,
            candidate=deferred.candidate,
            target_dir=target_dir,
            game=game,
            game_title=game_title,
            state=state,
            console=console,
            event_bus=event_bus,
            extract_archives=extract_archives,
            verification_available=verification_available,
            state_lock=state_lock,
            item_id=deferred.item_id,
        )
        attempts = list(deferred.attempts_summary)
        if result.status in ("acquired", "skipped", "unverified", "cancelled"):
            result.reason = ";".join(
                attempts + [f"{deferred.source_name}:{result.status}"]
            )
            return result
        attempts.append(
            f"{deferred.source_name}:{result.reason or result.status}"
        )
        resumed = self._dispatch_download(
            game_title,
            game,
            target_dir,
            region_priority,
            state,
            console=console,
            event_bus=event_bus,
            extract_archives=extract_archives,
            verification_available=verification_available,
            state_lock=state_lock,
            defer_torrent=False,
            start_index=deferred.source_index + 1,
            attempts_summary=attempts,
            check_acquired=False,
        )
        assert isinstance(resumed, DownloadResult)
        return resumed

    def _dispatch_download(
        self,
        game_title: str,
        game: GameEntry | None,
        target_dir: Path,
        region_priority: list[str],
        state: State,
        *,
        console: str,
        event_bus: EventBus | None,
        extract_archives: bool,
        verification_available: bool,
        state_lock: threading.Lock | None,
        defer_torrent: bool,
        start_index: int = 0,
        attempts_summary: list[str] | None = None,
        check_acquired: bool = True,
    ) -> DownloadResult | DeferredTorrentAttempt:
        item_id = hashlib.sha1(
            f"{console}\0{game_title}".encode("utf-8"), usedforsecurity=False
        ).hexdigest()
        if check_acquired:
            if state_lock is None:
                skipped = skip_if_acquired(
                    state,
                    game_title,
                    target_dir,
                    event_bus=event_bus,
                    item_id=item_id,
                )
            else:
                with state_lock:
                    skipped = skip_if_acquired(
                        state,
                        game_title,
                        target_dir,
                        event_bus=event_bus,
                        item_id=item_id,
                    )
            if skipped is not None:
                return skipped
        attempts = list(attempts_summary or [])
        published_dead_sources: set[str] = set()
        for source_index in range(start_index, len(self.source_names)):
            source_name = self.source_names[source_index]
            if event_bus is not None:
                event_bus.publish(
                    GameStartEvent(
                        game=game_title,
                        source=source_name,
                        console=console,
                        item_id=item_id,
                    )
                )
            if not self.allow_torrent and source_name in _TORRENT_SOURCES:
                attempts.append(f"{source_name}:skipped_no_torrent")
                continue
            if is_source_dead(source_name):
                attempts.append(f"{source_name}:dead")
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
                attempts.append(f"{source_name}:unsupported")
                continue
            try:
                candidate: DownloadCandidate | None = source.find_url_for_game(
                    game_title, region_priority
                )
            except SourceUnavailable as exc:
                _log.info("%s find failed for %s: %s", source_name, game_title, exc)
                attempts.append(f"{source_name}:find_failed({exc})")
                continue
            if candidate is None:
                attempts.append(f"{source_name}:no_match")
                continue
            download_source: Source = source
            if (candidate.extra or {}).get("transport") == "torrent":
                if self.torrent_coordinator is None:
                    attempts.append(f"{source_name}:qBittorrent_setup_required")
                    continue
                if defer_torrent:
                    return DeferredTorrentAttempt(
                        source_index=source_index,
                        source_name=source_name,
                        candidate=candidate,
                        attempts_summary=tuple(attempts),
                        item_id=item_id,
                    )
                download_source = TorrentTransferSource(
                    self.torrent_coordinator,
                    source_name=source_name,
                    game_title=game_title,
                    item_id=item_id,
                    state=state,
                    state_lock=state_lock,
                )
            result = download_game(
                source=download_source,
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
                item_id=item_id,
            )
            if event_bus is not None and result.reason:
                if "cloudflare" in result.reason.lower():
                    event_bus.publish(
                        CloudflareBlockEvent(source=source_name, status=0)
                    )
            if result.status in ("acquired", "skipped", "unverified", "cancelled"):
                result.reason = ";".join(attempts + [f"{source_name}:{result.status}"])
                return result
            attempts.append(
                f"{source_name}:{result.reason or result.status}"
            )
        final_reason = "; ".join(attempts) or "no sources configured"
        final_reason = (
            f"No downloadable file found. {final_reason}. "
            "Use a supported lawful source or your own game dump."
        )
        if event_bus is not None:
            event_bus.publish(
                GameFailedEvent(game=game_title, reason=final_reason, item_id=item_id)
            )
        return DownloadResult(
            status="failed",
            reason=final_reason,
        )
