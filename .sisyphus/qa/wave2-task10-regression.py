from __future__ import annotations
import difflib, subprocess, sys
from pathlib import Path

GOLDEN = Path(".sisyphus/golden")

def capture(*args):
    r = subprocess.run([sys.executable, "-m", "retrofetch", *args], capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        raise SystemExit(r.stderr or r.stdout)
    return r.stdout

def compare(args, golden_name):
    expected = (GOLDEN / golden_name).read_text(encoding="utf-8").split("# ---\n", 1)[1]
    actual = capture(*args)
    diff = list(difflib.unified_diff(expected.splitlines(True), actual.splitlines(True), fromfile=golden_name, tofile=" ".join(args)))
    assert not diff, "".join(diff[:30])

compare(["--version"], "cli-version.txt")
compare(["--help"], "cli-help.txt")
compare(["download", "--console", "mame", "--dry-run"], "cli-mame-dry-run.txt")
compare(["download", "--console", "nes", "--limit", "3", "--dry-run"], "cli-nes-dry-run.txt")
print("T10 regression: all goldens match")
