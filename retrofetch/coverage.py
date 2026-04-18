from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from retrofetch.config import _yaml_rt
from retrofetch.state import load_state


@dataclass
class ConsoleCoverage:
    shortname: str
    class_: str
    target: int
    acquired: int
    unverified: int
    failed: int
    pending: int
    status: str


@dataclass
class CoverageReport:
    by_console: list[ConsoleCoverage]
    status_totals: Counter
    class_totals: Counter
    failed_games: list[tuple[str, str, str]]
    timestamp: str


def compute_coverage(consoles_yml_path: Path, roms_root: Path) -> CoverageReport:
    consoles_yml_path = Path(consoles_yml_path)
    roms_root = Path(roms_root)
    data = _yaml_rt.load(consoles_yml_path.read_text(encoding="utf-8"))
    consoles = data.get("consoles", [])

    status_totals: Counter[str] = Counter()
    class_totals: Counter[str] = Counter()
    by_console: list[ConsoleCoverage] = []
    failed_games: list[tuple[str, str, str]] = []

    for entry in consoles:
        shortname = entry.get("shortname", "?")
        class_ = entry.get("class", "?")
        class_totals[class_] += 1
        if class_ in ("D", "E", "F"):
            reason = entry.get("skip_reason", "skipped")
            by_console.append(
                ConsoleCoverage(
                    shortname=shortname,
                    class_=class_,
                    target=0,
                    acquired=0,
                    unverified=0,
                    failed=0,
                    pending=0,
                    status=f"SKIPPED: {reason}",
                )
            )
            status_totals["skipped"] += 1
            continue
        state = load_state(shortname, roms_root)
        counts: Counter[str] = Counter(g.status for g in state.games)
        acquired = counts.get("acquired", 0)
        unverified = counts.get("unverified", 0)
        failed = counts.get("failed", 0)
        pending = counts.get("pending", 0)
        target = len(state.games)
        status_totals["acquired"] += acquired
        status_totals["unverified"] += unverified
        status_totals["failed"] += failed
        status_totals["pending"] += pending
        if target == 0:
            status = "not run"
        elif acquired == target:
            status = "complete"
        elif failed > 0 or unverified > 0:
            status = f"{acquired}/{target} acquired, {failed} failed, {unverified} unverified"
        else:
            status = f"{acquired}/{target} acquired"
        by_console.append(
            ConsoleCoverage(
                shortname=shortname,
                class_=class_,
                target=target,
                acquired=acquired,
                unverified=unverified,
                failed=failed,
                pending=pending,
                status=status,
            )
        )
        for g in state.games:
            if g.status == "failed":
                last = g.attempts[-1] if g.attempts else None
                reason = last.result if last else "unknown"
                failed_games.append((shortname, g.title, reason))

    return CoverageReport(
        by_console=by_console,
        status_totals=status_totals,
        class_totals=class_totals,
        failed_games=failed_games,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
