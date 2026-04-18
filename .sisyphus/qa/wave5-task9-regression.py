"""U9 full regression runner.

Invokes every QA scenario that exists in .sisyphus/qa/ (wave1-wave5) as a
subprocess, collects exit codes, and prints a summary. Exits 0 iff all
scenarios exit 0. Evidence: .sisyphus/evidence/ux-task-9-regression.txt
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
QA_DIR = REPO_ROOT / ".sisyphus" / "qa"
EVIDENCE = REPO_ROOT / ".sisyphus" / "evidence" / "ux-task-9-regression.txt"


# Exclude THIS runner + sample scripts + wave4-sourcesmoke which is network-live.
_EXCLUDE = {
    "wave5-task9-regression.py",
    "wave5-sample-noop.py",
    "wave1-sample-version-check.py",
    "wave4-task16-sourcesmoke.py",  # requires network; not deterministic in CI
}


def main() -> int:
    scenarios = sorted(
        p
        for p in QA_DIR.glob("wave*.py")
        if p.name not in _EXCLUDE
    )

    results: list[tuple[str, int, str]] = []
    for script in scenarios:
        r = subprocess.run(
            [sys.executable, str(script)],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
        )
        out = (r.stdout or "").strip().splitlines()
        last = out[-1] if out else ""
        results.append((script.name, r.returncode, last))

    passed = [r for r in results if r[1] == 0]
    failed = [r for r in results if r[1] != 0]

    lines = [f"total={len(results)} passed={len(passed)} failed={len(failed)}"]
    for name, code, last in results:
        tag = "PASS" if code == 0 else "FAIL"
        lines.append(f"[{tag}] rc={code} {name} :: {last}")

    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"U9 regression: {len(passed)}/{len(results)} scenarios passed")
    for name, code, last in failed:
        print(f"  FAIL rc={code} {name} :: {last}")

    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
