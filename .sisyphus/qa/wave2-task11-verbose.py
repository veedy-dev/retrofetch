from __future__ import annotations
import difflib, re, subprocess, sys
from pathlib import Path

# 1. Non-verbose regression: mame dry-run still matches golden
expected = (Path(".sisyphus/golden/cli-mame-dry-run.txt").read_text(encoding="utf-8")).split("# ---\n", 1)[1]
r1 = subprocess.run([sys.executable, "-m", "retrofetch", "download", "--console", "mame", "--dry-run"], capture_output=True, text=True, encoding="utf-8")
diff1 = list(difflib.unified_diff(expected.splitlines(True), r1.stdout.splitlines(True), fromfile="golden", tofile="actual"))
assert not diff1, "non-verbose regressed: " + "".join(diff1[:30])

# 2. Non-verbose regression: nes limit 3 dry-run still matches golden
expected2 = (Path(".sisyphus/golden/cli-nes-dry-run.txt").read_text(encoding="utf-8")).split("# ---\n", 1)[1]
r2 = subprocess.run([sys.executable, "-m", "retrofetch", "download", "--console", "nes", "--limit", "3", "--dry-run"], capture_output=True, text=True, encoding="utf-8")
diff2 = list(difflib.unified_diff(expected2.splitlines(True), r2.stdout.splitlines(True), fromfile="golden", tofile="actual"))
assert not diff2, "nes non-verbose regressed: " + "".join(diff2[:30])

# 3. Verbose produces event lines for nes dry-run
r3 = subprocess.run([sys.executable, "-m", "retrofetch", "download", "--console", "nes", "--limit", "3", "--verbose", "--dry-run"], capture_output=True, text=True, encoding="utf-8")
# Dry-run synthetic events: GameStartEvent -> "Starting ... from dry-run" (color tags stripped by Rich when stdout is not a TTY, but the keyword is still present)
# Look for keyword substrings present in formatter output
assert r3.returncode == 0, f"verbose exit {r3.returncode}: {r3.stderr}"
arrow_lines = [l for l in r3.stdout.splitlines() if re.search(r"Starting|Acquired|Failed|Loading DAT", l)]
assert len(arrow_lines) >= 1, f"no event lines in verbose output: {r3.stdout!r}"

# 4. No emoji pictographs in verbose output (plain unicode arrows OK, but no :smile: style or pictograph planes)
emoji_pattern = re.compile(r"[\U0001F300-\U0001FAFF]|:smiley:|:joy:|:smile:")
assert not emoji_pattern.search(r3.stdout), f"emoji contamination: {r3.stdout!r}"

print("T11 verbose: OK")
print(f"  non-verbose mame:   {len(r1.stdout)} bytes, golden match")
print(f"  non-verbose nes:    {len(r2.stdout)} bytes, golden match")
print(f"  verbose nes:        {len(arrow_lines)} event lines, no emoji")
