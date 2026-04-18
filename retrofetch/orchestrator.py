from __future__ import annotations

import logging
import re
import shutil
import threading
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from retrofetch.config import Config
from retrofetch.dat import DatEntry, parse_dat
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
    skipped: bool = False
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
        report.skipped = True
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
        dats_dir = Path(__file__).resolve().parent.parent / "dats"
    dat_path = find_dat_for_console(short, consoles_yml, dats_dir)
    if event_bus is not None:
        event_bus.publish(
            DatLoadStartEvent(
                console=short,
                dat_name=dat_path.name if dat_path is not None else "(none)",
            )
        )
    if dat_path is not None:
        try:
            dat = parse_dat(dat_path)
        except Exception as exc:
            _log.warning("failed to parse DAT for %s: %s", short, exc)
            dat = None
    if event_bus is not None:
        event_bus.publish(
            DatLoadDoneEvent(console=short, games_loaded=len(dat.games) if dat else 0)
        )

    source_names = config.source_fallback_by_class.get(klass, [])
    dispatcher = SourceDispatcher(
        console_entry=console_entry,
        source_names=source_names,
        allow_torrent=allow_torrent,
    )

    state = load_state(short, config.roms_root)

    groups = group_by_base_title(wantlist)
    for base_title, variants in groups.items():
        if stop_event is not None and stop_event.is_set():
            break
        report.attempted += 1
        game_entry = None
        if dat is not None:
            for g in dat.games:
                if strip_disc_marker(g.name).lower() == base_title.lower():
                    game_entry = g
                    break
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
            )
            if result.status == "acquired":
                acquired_any = True
            elif result.status == "unverified":
                report.unverified += 1
            else:
                report.failed += 1
            if not dry_run:
                save_state(state, config.roms_root)
        if acquired_any:
            report.acquired += 1

    if not dry_run:
        save_state(state, config.roms_root)
    return report
