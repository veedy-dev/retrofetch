from __future__ import annotations
import pathlib

hits: list[str] = []
for py in pathlib.Path("retrofetch").rglob("*.py"):
    text = py.read_text(encoding="utf-8")
    for i, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if "progress_cb" in line:
            hits.append(f"{py}:{i}: {line.strip()}")

if hits:
    for h in hits:
        print(h)
    raise SystemExit(f"progress_cb remnants: {len(hits)}")
print("T10 grep: no progress_cb in production code")
