from __future__ import annotations

from pathlib import Path

from retrofetch.coverage import CoverageReport, compute_coverage


def write_coverage_markdown(report: CoverageReport, output_path: Path) -> Path:
    lines: list[str] = []
    lines.append("# retrofetch Coverage Report")
    lines.append("")
    lines.append(f"Generated: {report.timestamp}")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Classes: {dict(sorted(report.class_totals.items()))}")
    lines.append(f"- Game statuses: {dict(sorted(report.status_totals.items()))}")
    lines.append("")
    lines.append("## Per-console")
    lines.append("")
    lines.append(
        "| Console | Class | Target | Acquired | Unverified | Failed | Pending | Status |"
    )
    lines.append("|---|---|---|---|---|---|---|---|")
    for console in report.by_console:
        lines.append(
            f"| {console.shortname} | {console.class_} | {console.target} | {console.acquired} | {console.unverified} | "
            f"{console.failed} | {console.pending} | {console.status} |"
        )
    lines.append("")

    if report.failed_games:
        lines.append("## Failed games")
        lines.append("")
        for shortname, title, reason in report.failed_games:
            lines.append(f"- {shortname}: {title} — {reason}")
        lines.append("")

    output_path = Path(output_path)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path


def generate_coverage_report(
    consoles_yml_path: Path,
    roms_root: Path,
    output_path: Path = Path("coverage.md"),
) -> Path:
    report = compute_coverage(consoles_yml_path, roms_root)
    return write_coverage_markdown(report, output_path)
