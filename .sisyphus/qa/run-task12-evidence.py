from __future__ import annotations

import pathlib
import subprocess
import sys

BASE = pathlib.Path('.sisyphus/evidence')
ITEMS = [
    ('.sisyphus/qa/wave3-task12-launch.py', BASE / 'tui-task-12-launch.txt'),
    ('.sisyphus/qa/wave3-task12-msys2.py', BASE / 'tui-task-12-msys2.txt'),
    ('.sisyphus/qa/wave3-task12-noconfig.py', BASE / 'tui-task-12-noconfig.txt'),
]

for script, out in ITEMS:
    result = subprocess.run(
        [sys.executable, script],
        capture_output=True,
        text=True,
        encoding='utf-8',
    )
    out.write_text((result.stdout or '') + (result.stderr or ''), encoding='utf-8')
    print(f'{script} -> {result.returncode}')
    if result.returncode != 0:
        raise SystemExit(result.returncode)
