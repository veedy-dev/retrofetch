from __future__ import annotations
from pathlib import Path
from retrofetch.coverage import compute_coverage, CoverageReport

report = compute_coverage(Path("consoles.yml"), Path("ROMs"))
assert isinstance(report, CoverageReport)
assert len(report.by_console) == 178, f"expected 178 rows, got {len(report.by_console)}"
print(f"T9 compute_coverage: OK ({len(report.by_console)} consoles)")
