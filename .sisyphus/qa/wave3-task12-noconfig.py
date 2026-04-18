from __future__ import annotations
import subprocess, sys, tempfile

with tempfile.TemporaryDirectory() as td:
    r = subprocess.run(
        [sys.executable, "-m", "retrofetch", "tui", "--config", "./nope.yml"],
        cwd=td,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert r.returncode == 2, f"expected exit 2 for missing config, got {r.returncode}"
    combined = (r.stdout + r.stderr).lower()
    assert "config" in combined or "not found" in combined or "interactive terminal" in combined, \
        f"expected error message mentioning config/not-found/tty: {combined!r}"
print(f"T12 noconfig: OK (exit 2)")
