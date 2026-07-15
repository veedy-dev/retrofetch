from __future__ import annotations

import hashlib
import logging
import re
import shutil
import threading
from collections import defaultdict
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from retrofetch import _resources
from retrofetch.config import Config
from retrofetch.dat import DatEntry, GameEntry as DatGameEntry, parse_dat
from retrofetch.dat_fetch import find_dat_for_console
from retrofetch.dispatcher import DeferredTorrentAttempt, SourceDispatcher
from retrofetch.events import (
    DatLoadDoneEvent,
    DatLoadStartEvent,
    EventBus,
    GameDoneEvent,
    GameCancelledEvent,
    GameStartEvent,
)
from retrofetch.state import load_state, save_state, update_game
from retrofetch.sources import DownloadCancelled, SourceUnavailable
from retrofetch.torrent import PreparedTorrent, TorrentBatchItem, TorrentCoordinator

_log = logging.getLogger(__name__)

_DISC_PATTERN = re.compile(r"\s*\((?:Disc|Disk)\s*\d+[^)]*\)", re.IGNORECASE)

_SIZE_ESTIMATE_BY_CLASS = {
    "A": 4 * 1024 * 1024,
    "B": 700 * 1024 * 1024,
    "C": 4 * 1024 * 1024 * 1024,
}


@dataclass
class RunReport:
    console: str
    attempted: int = 0
    acquired: int = 0
    failed: int = 0
    unverified: int = 0
    skipped: int = 0
    cancelled: int = 0
    skip_reason: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class _DeferredTorrentWork:
    dispatcher: SourceDispatcher
    attempt: DeferredTorrentAttempt
    game_title: str
    game: DatGameEntry | None


def strip_disc_marker(title: str) -> str:
    return _DISC_PATTERN.sub("", title).strip()


def group_by_base_title(titles: list[str]) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = defaultdict(list)
    for title in titles:
        base = strip_disc_marker(title)
        groups[base].append(title)
    return dict(groups)


def estimate_total_bytes(titles: list[str], klass: str) -> int:
    per_game = _SIZE_ESTIMATE_BY_CLASS.get(klass, 50 * 1024 * 1024)
    return per_game * len(titles)


def preflight_disk(
    roms_root: Path,
    estimated_bytes: int,
    margin_bytes: int = 1 * 1024 * 1024 * 1024,
) -> tuple[bool, int]:
    usage = shutil.disk_usage(roms_root)
    required = estimated_bytes + margin_bytes
    return usage.free >= required, usage.free


def run_console(
    console_entry: dict[str, Any],
    wantlist: list[str],
    config: Config,
    allow_torrent: bool,
    consoles_yml: dict[str, Any],
    stop_event: threading.Event | None = None,
    *,
    event_bus: EventBus | None = None,
    dry_run: bool = False,
    torrent_setup_callback: Callable[[], bool] | None = None,
) -> RunReport:
    short = str(console_entry.get("shortname", "?"))
    klass = str(console_entry.get("class", "?"))
    report = RunReport(console=short)
    allow_torrent = allow_torrent and config.torrent_mode != "disabled"

    if klass in ("D", "E", "F"):
        report.skipped = 1
        report.skip_reason = str(console_entry.get("skip_reason") or "out of scope")
        return report

    target_dir = Path(config.roms_root) / short
    target_dir.mkdir(parents=True, exist_ok=True)

    estimated = estimate_total_bytes(wantlist, klass)
    ok, free = preflight_disk(Path(config.roms_root), estimated)
    if not ok:
        report.error = f"insufficient disk: estimated {estimated} bytes needed but only {free} free"
        return report

    dat: DatEntry | None = None
    dats_dir = Path("dats")
    if not dats_dir.exists():
        dats_dir = _resources.find_data_file("dats")
    dat_path = find_dat_for_console(short, consoles_yml, dats_dir)
    if event_bus is not None:
        event_bus.publish(
            DatLoadStartEvent(
                console=short,
                dat_name=dat_path.name if dat_path is not None else "(none)",
            )
        )
    dat_status = "missing"
    dat_detail = f"DAT not available for {short}; downloads are unverified."
    if dat_path is not None:
        try:
            dat = parse_dat(dat_path)
            if dat.games:
                dat_status = "loaded"
                dat_detail = None
            else:
                dat = None
                dat_status = "empty"
                dat_detail = (
                    f"DAT for {short} parsed but contains 0 games; "
                    "downloads are unverified."
                )
        except Exception as exc:
            _log.warning("failed to parse DAT for %s: %s", short, exc)
            dat = None
            dat_status = "corrupt"
            dat_detail = f"DAT for {short} could not be parsed; downloads are unverified."
    if event_bus is not None:
        event_bus.publish(
            DatLoadDoneEvent(
                console=short,
                games_loaded=len(dat.games) if dat else 0,
                status=dat_status,
                detail=dat_detail,
            )
        )

    source_names = config.source_fallback_by_class.get(klass, [])
    state = load_state(short, config.roms_root)
    verification_available = dat is not None and bool(dat.games)
    max_workers = max(1, min(3, int(config.max_concurrent_downloads or 1)))
    report_lock = threading.Lock()
    state_lock = threading.Lock()
    deferred_lock = threading.Lock()
    deferred_torrents: list[_DeferredTorrentWork] = []
    games_by_base_title: dict[str, DatGameEntry] = {}
    if dat is not None:
        for game in dat.games:
            games_by_base_title.setdefault(strip_disc_marker(game.name).lower(), game)
    dispatcher_local = threading.local()
    torrent_coordinator = (
        TorrentCoordinator(
            config,
            stop_event,
            setup_callback=torrent_setup_callback,
        )
        if allow_torrent and not dry_run and config.torrent_mode != "disabled"
        else None
    )

    def find_game_entry(base_title: str) -> DatGameEntry | None:
        return games_by_base_title.get(base_title.lower())

    def get_dispatcher() -> SourceDispatcher:
        dispatcher = getattr(dispatcher_local, "dispatcher", None)
        if dispatcher is None:
            dispatcher = SourceDispatcher(
                console_entry=console_entry,
                source_names=source_names,
                allow_torrent=allow_torrent,
            )
            dispatcher.torrent_coordinator = torrent_coordinator
            dispatcher_local.dispatcher = dispatcher
        return dispatcher

    terminal_titles: set[str] = set()

    def item_id_for(title: str) -> str:
        return hashlib.sha1(
            f"{short}\0{title}".encode("utf-8"), usedforsecurity=False
        ).hexdigest()

    def record_result(status: str, title: str) -> None:
        with report_lock:
            report.attempted += 1
            terminal_titles.add(title)
            if status == "acquired":
                report.acquired += 1
            elif status == "unverified":
                report.unverified += 1
            elif status == "skipped":
                report.skipped += 1
            elif status == "cancelled":
                report.cancelled += 1
            elif status != "acquired":
                report.failed += 1

    def process_group(base_title: str, variants: list[str]) -> None:
        if stop_event is not None and stop_event.is_set():
            return
        game_entry = find_game_entry(base_title)
        dispatcher = get_dispatcher()
        for variant in variants:
            if stop_event is not None and stop_event.is_set():
                break
            if dry_run:
                with report_lock:
                    report.attempted += 1
                    terminal_titles.add(variant)
                if event_bus is not None:
                    item_id = item_id_for(variant)
                    event_bus.publish(
                        GameStartEvent(
                            game=variant,
                            source="dry-run",
                            console=short,
                            item_id=item_id,
                        )
                    )
                    event_bus.publish(
                        GameDoneEvent(
                            game=variant,
                            source="dry-run",
                            size=0,
                            sha1=None,
                            item_id=item_id,
                        )
                    )
                continue
            try:
                dispatch = getattr(dispatcher, "dispatch_until_torrent", None)
                if dispatch is None:
                    dispatch = dispatcher.dispatch_download
                result = dispatch(
                    game_title=variant,
                    game=game_entry,
                    target_dir=target_dir,
                    region_priority=config.region_priority,
                    state=state,
                    console=short,
                    event_bus=event_bus,
                    extract_archives=config.extract_archives,
                    verification_available=verification_available,
                    state_lock=state_lock,
                )
                if isinstance(result, DeferredTorrentAttempt):
                    with deferred_lock:
                        deferred_torrents.append(
                            _DeferredTorrentWork(
                                dispatcher=dispatcher,
                                attempt=result,
                                game_title=variant,
                                game=game_entry,
                            )
                        )
                    continue
                status = result.status
            except Exception:
                _log.exception("download worker failed for %s", variant)
                status = "failed"
            record_result(status, variant)
            if not dry_run:
                with state_lock:
                    save_state(state, config.roms_root)

    groups = group_by_base_title(wantlist)
    work_items = list(groups.items())
    try:
        if max_workers == 1 or len(work_items) <= 1:
            for base_title, variants in work_items:
                if stop_event is not None and stop_event.is_set():
                    break
                process_group(base_title, variants)
        else:
            iterator = iter(work_items)
            futures: dict[Future[None], tuple[str, list[str]]] = {}
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                for _ in range(max_workers):
                    if stop_event is not None and stop_event.is_set():
                        break
                    try:
                        item = next(iterator)
                    except StopIteration:
                        break
                    futures[executor.submit(process_group, item[0], item[1])] = item

                while futures:
                    done, _pending = wait(futures, return_when=FIRST_COMPLETED)
                    for future in done:
                        item = futures.pop(future, None)
                        try:
                            future.result()
                        except Exception:
                            _log.exception("download worker failed for %s", item)
                        if stop_event is not None and stop_event.is_set():
                            continue
                        try:
                            item = next(iterator)
                        except StopIteration:
                            continue
                        futures[executor.submit(process_group, item[0], item[1])] = item

        if deferred_torrents and not dry_run:
            grouped: dict[str, list[_DeferredTorrentWork]] = defaultdict(list)
            prepared_results: dict[str, PreparedTorrent | SourceUnavailable] = {}
            for work in deferred_torrents:
                infohash = (work.attempt.candidate.extra or {}).get(
                    "torrent_infohash"
                )
                if not isinstance(infohash, str) or not re.fullmatch(
                    r"[0-9a-f]{40}", infohash
                ):
                    prepared_results[work.attempt.item_id] = SourceUnavailable(
                        "torrent candidate has an invalid infohash", retryable=False
                    )
                    continue
                grouped[infohash].append(work)

            for same_hash in grouped.values():
                if stop_event is not None and stop_event.is_set():
                    outcomes: dict[str, PreparedTorrent | SourceUnavailable] = {
                        work.attempt.item_id: DownloadCancelled()
                        for work in same_hash
                    }
                elif torrent_coordinator is None:
                    outcomes = {
                        work.attempt.item_id: SourceUnavailable(
                            "qBittorrent setup is unavailable", retryable=False
                        )
                        for work in same_hash
                    }
                else:
                    batch = [
                        TorrentBatchItem(
                            candidate=work.attempt.candidate,
                            target_dir=target_dir,
                            game_title=work.game_title,
                            item_id=work.attempt.item_id,
                        )
                        for work in same_hash
                    ]
                    try:
                        outcomes = torrent_coordinator.transfer_many(
                            batch,
                            state=state,
                            state_lock=state_lock,
                            event_bus=event_bus,
                        )
                    except DownloadCancelled as exc:
                        outcomes = {
                            work.attempt.item_id: exc for work in same_hash
                        }
                    except Exception as exc:
                        _log.exception("grouped torrent transfer failed")
                        failure = SourceUnavailable(
                            f"grouped torrent transfer failed: {exc}",
                            retryable=False,
                        )
                        outcomes = {
                            work.attempt.item_id: failure for work in same_hash
                        }
                prepared_results.update(outcomes)

            for work in deferred_torrents:
                outcome = prepared_results.get(work.attempt.item_id)
                if stop_event is not None and stop_event.is_set():
                    outcome = DownloadCancelled()
                if outcome is None:
                    outcome = SourceUnavailable(
                        "grouped torrent transfer produced no item result",
                        retryable=False,
                    )
                try:
                    result = work.dispatcher.resume_download(
                        work.attempt,
                        prepared=(
                            outcome if isinstance(outcome, PreparedTorrent) else None
                        ),
                        transfer_error=(
                            outcome if isinstance(outcome, Exception) else None
                        ),
                        game_title=work.game_title,
                        game=work.game,
                        target_dir=target_dir,
                        region_priority=config.region_priority,
                        state=state,
                        console=short,
                        event_bus=event_bus,
                        extract_archives=config.extract_archives,
                        verification_available=verification_available,
                        state_lock=state_lock,
                    )
                    status = result.status
                except Exception:
                    _log.exception(
                        "download worker failed while finalizing %s",
                        work.game_title,
                    )
                    status = "failed"
                record_result(status, work.game_title)
                with state_lock:
                    save_state(state, config.roms_root)

        if stop_event is not None and stop_event.is_set() and not dry_run:
            with report_lock:
                cancelled_titles = [
                    title for title in wantlist if title not in terminal_titles
                ]
                report.cancelled += len(cancelled_titles)
                report.attempted += len(cancelled_titles)
                terminal_titles.update(cancelled_titles)
            for title in cancelled_titles:
                item_id = item_id_for(title)
                with state_lock:
                    update_game(
                        state,
                        title,
                        item_id=item_id,
                        status="cancelled",
                        phase="terminal",
                        outcome="cancelled",
                        verification="not_applicable",
                    )
                if event_bus is not None:
                    event_bus.publish(
                        GameCancelledEvent(
                            title, "run cancelled", item_id=item_id
                        )
                    )

        if not dry_run:
            with state_lock:
                save_state(state, config.roms_root)
            report.attempted = (
                report.acquired
                + report.failed
                + report.unverified
                + report.skipped
                + report.cancelled
            )
    finally:
        if torrent_coordinator is not None:
            try:
                torrent_coordinator.close()
            except Exception:
                _log.exception("failed to close qBittorrent coordinator")
    return report
