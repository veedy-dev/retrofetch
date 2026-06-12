import sys
import time
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from retrofetch.config import Config
from retrofetch.wantlist_cache import get_or_fetch_wantlist

SOURCE_KEYS = (
    "minerva_path",
    "archive_org_identifier",
    "romsfun_slug",
    "romsretro_slug",
    "vimm_slug",
    "coolrom_slug",
)


def has_any_source(entry: dict) -> bool:
    return any(entry.get(k) for k in SOURCE_KEYS)


def main() -> int:
    config = Config(roms_root=Path("ROMs"), cache_dir=Path(".cache-e2e-test"))
    data = yaml.safe_load(Path("consoles.yml").read_text(encoding="utf-8"))
    consoles = data.get("consoles", data) if isinstance(data, dict) else data
    abc = [c for c in consoles if c.get("class") in ("A", "B", "C")]
    rows: list[tuple[str, str, int, str]] = []
    for entry in abc:
        short = str(entry.get("shortname", "?"))
        cls = str(entry.get("class", "?"))
        try:
            titles, cached = get_or_fetch_wantlist(entry, None, config, 0)
            count = len(titles)
            if count > 0:
                status = "ok"
            elif not has_any_source(entry):
                status = "no-source"
            else:
                status = "empty"
        except Exception as exc:
            count = 0
            status = "error:" + str(exc).replace(",", ";").replace("\n", " ")[:120]
            cached = False
        rows.append((short, cls, count, status))
        print(f"{short}: {count} titles ({status})", flush=True)
        if not cached:
            time.sleep(1)

    out = Path(".omo/evidence/task-20-breadth.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = ["console,class,count,status"]
    lines += [f"{s},{c},{n},{st}" for s, c, n, st in rows]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")

    total = len(rows)
    ok50 = sum(1 for _, _, n, _ in rows if n >= 50)
    silent = [s for s, _, n, st in rows if n == 0 and st == "empty"]
    pct = 100.0 * ok50 / total if total else 0.0
    print(f"TOTAL={total} OK50={ok50} ({pct:.1f}%) SILENT_EMPTY={len(silent)}")
    if silent:
        print("Silent empties:", ", ".join(silent))
    passed = pct >= 80.0 and not silent
    print("PASS" if passed else "FAIL")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
