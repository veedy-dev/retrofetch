from __future__ import annotations

import logging
import re
import shutil
import threading
from collections import defaultdict
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from retrofetch import _resources
from retrofetch.config import Config
from retrofetch.dat import DatEntry, GameEntry as DatGameEntry, parse_dat
from retrofetch.dat_fetch import find_dat_for_console
from retrofetch.dispatcher import SourceDispatcher
from retrofetch.events import (
    DatLoadDoneEvent,
    DatLoadStartEvent,
    EventBus,
    GameDoneEvent,
    GameStartEvent,
)
from retrofetch.state import load_state, save_state

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
    skip_reason: str | None = None
    error: str | None = None


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
) -> RunReport:
    short = str(console_entry.get("shortname", "?"))
    klass = str(console_entry.get("class", "?"))
    report = RunReport(console=short)

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

    def find_game_entry(base_title: str) -> DatGameEntry | None:
        if dat is None:
            return None
        for game in dat.games:
            if strip_disc_marker(game.name).lower() == base_title.lower():
                return game
        return None

    def record_result(status: str) -> None:
        with report_lock:
            if status == "unverified":
                report.unverified += 1
            elif status == "skipped":
                report.skipped += 1
            elif status != "acquired":
                report.failed += 1

    def process_group(base_title: str, variants: list[str]) -> bool:
        if stop_event is not None and stop_event.is_set():
            return False
        with report_lock:
            report.attempted += 1
        game_entry = find_game_entry(base_title)
        dispatcher = SourceDispatcher(
            console_entry=console_entry,
            source_names=source_names,
            allow_torrent=allow_torrent,
        )
        acquired_any = False
        for variant in variants:
            if stop_event is not None and stop_event.is_set():
                break
            if dry_run:
                if event_bus is not None:
                    event_bus.publish(
                        GameStartEvent(game=variant, source="dry-run", console=short)
                    )
                    event_bus.publish(
                        GameDoneEvent(game=variant, source="dry-run", size=0, sha1=None)
                    )
                continue
            result = dispatcher.dispatch_download(
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
            if result.status == "acquired":
                acquired_any = True
            record_result(result.status)
            if not dry_run:
                with state_lock:
                    save_state(state, config.roms_root)
        return acquired_any

    groups = group_by_base_title(wantlist)
    work_items = list(groups.items())
    if max_workers == 1 or len(work_items) <= 1:
        for base_title, variants in work_items:
            try:
                acquired = process_group(base_title, variants)
            except Exception:
                _log.exception("download worker failed for %s", base_title)
                acquired = False
                with report_lock:
                    report.failed += 1
            if acquired:
                with report_lock:
                    report.acquired += 1
            if stop_event is not None and stop_event.is_set():
                break
    else:
        iterator = iter(work_items)
        futures: dict[Future[bool], tuple[str, list[str]]] = {}
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
                        acquired = future.result()
                    except Exception:
                        _log.exception("download worker failed for %s", item)
                        acquired = False
                        with report_lock:
                            report.failed += 1
                    if acquired:
                        with report_lock:
                            report.acquired += 1
                    if stop_event is not None and stop_event.is_set():
                        continue
                    try:
                        item = next(iterator)
                    except StopIteration:
                        continue
                    futures[executor.submit(process_group, item[0], item[1])] = item

    if not dry_run:
        with state_lock:
            save_state(state, config.roms_root)
    return report
