import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from retrofetch.sources.minerva_http import MinervaHttpSource


def main() -> int:
    data = yaml.safe_load(Path("consoles.yml").read_text(encoding="utf-8"))
    consoles = data.get("consoles", data) if isinstance(data, dict) else data
    psp = next(c for c in consoles if c.get("shortname") == "psp")
    titles = MinervaHttpSource(psp).list_popular(0, ["USA", "World", "Europe", "Japan"])
    verdict = "PASS" if len(titles) >= 1000 else "FAIL"
    print(f"PSP catalog count: {len(titles)}")
    print("Sample:", titles[:5])
    out = Path(".omo/evidence/task-20-psp.txt")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        "PSP headline catalog via MinervaHttpSource (real consoles.yml entry)\n"
        f"count={len(titles)}\n"
        f"first5={titles[:5]}\n"
        f"assert count>=1000: {verdict}\n",
        encoding="utf-8",
    )
    print(f"{verdict}: PSP catalog >= 1000 titles")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
