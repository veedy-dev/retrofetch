from __future__ import annotations
import os, subprocess, sys

env = os.environ.copy()
env["MSYSTEM"] = "MINGW64"
r = subprocess.run(
    [sys.executable, "-m", "retrofetch", "tui"],
    env=env,
    capture_output=True,
    text=True,
    encoding="utf-8",
)
assert r.returncode == 2, f"expected exit 2, got {r.returncode}: stdout={r.stdout!r} stderr={r.stderr!r}"
combined = (r.stdout + r.stderr).lower()
assert "msys2" in combined or "interactive terminal" in combined or "mingw" in combined, \
    f"expected refusal message, got: {combined!r}"
print(f"T12 msys2-refusal: OK (exit 2, msg={combined[:100]!r})")
