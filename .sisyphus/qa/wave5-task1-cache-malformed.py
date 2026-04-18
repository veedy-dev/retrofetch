from __future__ import annotations

import importlib
import sys
import tempfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

ranker: Any = importlib.import_module("retrofetch.ranker")
cache_mod: Any = importlib.import_module("retrofetch.wantlist_cache")
Config = importlib.import_module("retrofetch.config").Config


def _fake_console_entry() -> dict[str, object]:
    return {"shortname": "nes", "class": "A"}


def _write_evidence(slug: str, text: str) -> None:
    path = Path(f".sisyphus/evidence/ux-task-1-{slug}.txt")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main() -> None:
    calls = {"count": 0}

    def fake_get_wantlist(*, console_entry, overrides, config, limit):
        calls["count"] += 1
        return ["Metroid", "Kid Icarus"][:limit]

    ranker.get_wantlist = fake_get_wantlist
    cache_mod.get_wantlist = fake_get_wantlist

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        cache_dir = root / "cache"
        config = Config(roms_root=root / "ROMs", cache_dir=cache_dir)
        path = cache_mod.cache_path(cache_dir, "nes")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("not a valid json {", encoding="utf-8")

        assert cache_mod.load_cached(cache_dir, "nes") is None

        titles, from_cache = cache_mod.get_or_fetch_wantlist(_fake_console_entry(), None, config, 5)
        assert from_cache is False
        assert calls["count"] == 1
        assert titles == ["Metroid", "Kid Icarus"]

        _write_evidence(
            "cache-malformed",
            "\n".join(
                [
                    f"cache_file={path}",
                    "load_cached=None",
                    f"from_cache={from_cache}",
                    f"call_count={calls['count']}",
                    f"titles={titles}",
                ]
            ),
        )

    print("OK: malformed cache falls back to fetch")


if __name__ == "__main__":
    try:
        main()
    except AssertionError:
        raise SystemExit(1)
