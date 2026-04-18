from __future__ import annotations

import importlib
import json
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
        return ["Super Mario Bros.", "The Legend of Zelda"][:limit]

    ranker.get_wantlist = fake_get_wantlist
    cache_mod.get_wantlist = fake_get_wantlist

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        cache_dir = root / "cache"
        config = Config(roms_root=root / "ROMs", cache_dir=cache_dir)
        console_entry = _fake_console_entry()
        expected_path = cache_mod.cache_path(cache_dir, "nes")

        titles1, from_cache1 = cache_mod.get_or_fetch_wantlist(console_entry, None, config, 5)
        assert from_cache1 is False
        assert calls["count"] == 1
        assert expected_path.exists()

        payload = json.loads(expected_path.read_text(encoding="utf-8"))
        assert payload["console"] == "nes"
        assert payload["ttl_hours"] == cache_mod.DEFAULT_TTL_HOURS
        assert payload["titles"] == titles1

        titles2, from_cache2 = cache_mod.get_or_fetch_wantlist(console_entry, None, config, 5)
        assert from_cache2 is True
        assert calls["count"] == 1
        assert titles2 == titles1

        cache_mod.invalidate(cache_dir, "nes")
        assert not expected_path.exists()

        titles3, from_cache3 = cache_mod.get_or_fetch_wantlist(console_entry, None, config, 5)
        assert from_cache3 is False
        assert calls["count"] == 2
        assert titles3 == titles1

        _write_evidence(
            "cache",
            "\n".join(
                [
                    f"cache_file={expected_path}",
                    f"first_from_cache={from_cache1}",
                    f"second_from_cache={from_cache2}",
                    f"third_from_cache={from_cache3}",
                    f"call_count={calls['count']}",
                    f"titles={titles3}",
                ]
            ),
        )

    print("OK: cache cold miss, warm hit, invalidate re-fetch")


if __name__ == "__main__":
    try:
        main()
    except AssertionError:
        raise SystemExit(1)
