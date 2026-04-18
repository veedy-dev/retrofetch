"""T23 exit2-noconfig: missing --config path triggers preflight refusal with exit 2."""
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
    assert r.returncode == 2, f"expected exit 2, got {r.returncode}: stdout={r.stdout!r} stderr={r.stderr!r}"
print(f"T23 exit2-noconfig: OK (exit 2)")
