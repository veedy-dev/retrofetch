from __future__ import annotations

import difflib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GOLDEN_DIR = ROOT / ".sisyphus" / "golden"


def load_body(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    marker = "# ---\n"
    if marker not in text:
        raise SystemExit(f"missing golden separator: {path}")
    return text.split(marker, 1)[1]


def capture(*args: str) -> str:
    proc = subprocess.run(
        [sys.executable, "-m", "retrofetch", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if proc.returncode != 0:
        raise SystemExit(proc.stderr or proc.stdout)
    return proc.stdout


def compare(name: str, expected_file: str, actual: str) -> None:
    expected = load_body(GOLDEN_DIR / expected_file)
    if actual == expected:
        return
    diff = "".join(
        difflib.unified_diff(
            expected.splitlines(keepends=True),
            actual.splitlines(keepends=True),
            fromfile=f"golden/{expected_file}",
            tofile=f"actual/{name}",
        )
    )
    raise SystemExit(diff)


def main() -> None:
    compare("version", "cli-version.txt", capture("--version"))
    compare("help", "cli-help.txt", capture("--help"))
    compare("mame-dry-run", "cli-mame-dry-run.txt", capture("download", "--console", "mame", "--dry-run"))
    compare("nes-dry-run", "cli-nes-dry-run.txt", capture("download", "--console", "nes", "--limit", "3", "--dry-run"))
    print("goldens ok")


if __name__ == "__main__":
    main()
