"""Coverage report generator."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import yaml

from retrofetch.state import load_state


def generate_coverage_report(
    consoles_yml_path: Path,
    roms_root: Path,
    output_path: Path = Path("coverage.md"),
) -> Path:
    consoles_yml_path = Path(consoles_yml_path)
    roms_root = Path(roms_root)
    data = yaml.safe_load(consoles_yml_path.read_text(encoding="utf-8"))
    consoles = data.get("consoles", [])

    lines: list[str] = []
    lines.append("# retrofetch Coverage Report")
    lines.append("")
    lines.append(f"Generated: {datetime.now(timezone.utc).isoformat()}")
    lines.append("")

    status_totals: Counter[str] = Counter()
    class_totals: Counter[str] = Counter()
    rows: list[tuple[str, str, int, int, int, int, int, str]] = []
    failed_games: list[tuple[str, str, str]] = []

    for entry in consoles:
        shortname = entry.get("shortname", "?")
        class_ = entry.get("class", "?")
        class_totals[class_] += 1
        if class_ in ("D", "E", "F"):
            reason = entry.get("skip_reason", "skipped")
            rows.append((shortname, class_, 0, 0, 0, 0, 0, f"SKIPPED: {reason}"))
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
        rows.append(
            (shortname, class_, target, acquired, unverified, failed, pending, status)
        )
        for g in state.games:
            if g.status == "failed":
                last = g.attempts[-1] if g.attempts else None
                reason = last.result if last else "unknown"
                failed_games.append((shortname, g.title, reason))

    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Classes: {dict(sorted(class_totals.items()))}")
    lines.append(f"- Game statuses: {dict(sorted(status_totals.items()))}")
    lines.append("")
    lines.append("## Per-console")
    lines.append("")
    lines.append(
        "| Console | Class | Target | Acquired | Unverified | Failed | Pending | Status |"
    )
    lines.append("|---|---|---|---|---|---|---|---|")
    for (
        shortname,
        class_,
        target,
        acquired,
        unverified,
        failed,
        pending,
        status,
    ) in rows:
        lines.append(
            f"| {shortname} | {class_} | {target} | {acquired} | {unverified} | "
            f"{failed} | {pending} | {status} |"
        )
    lines.append("")

    if failed_games:
        lines.append("## Failed games")
        lines.append("")
        for shortname, title, reason in failed_games:
            lines.append(f"- {shortname}: {title} — {reason}")
        lines.append("")

    output_path = Path(output_path)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path
