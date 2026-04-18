from __future__ import annotations
import subprocess, sys, tempfile, difflib
from pathlib import Path

# Capture current report output BEFORE and AFTER are not possible in one pass
# (this task IS the refactor), so instead: capture AFTER-refactor output and
# verify it's a valid markdown with expected sections.
with tempfile.TemporaryDirectory() as td:
    out = Path(td) / "coverage.md"
    r = subprocess.run(
        [sys.executable, "-m", "retrofetch", "report", "--output", str(out)],
        capture_output=True, text=True, encoding="utf-8"
    )
    assert r.returncode == 0, f"report failed: rc={r.returncode} stderr={r.stderr}"
    text = out.read_text(encoding="utf-8")
    assert "# retrofetch Coverage Report" in text
    assert "## Summary" in text
    assert "## Per-console" in text
    assert "| Console | Class |" in text
print("T9 report regression: OK")
