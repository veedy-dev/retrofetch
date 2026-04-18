from __future__ import annotations

import importlib
import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
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
        return ["Mega Man 2", "Castlevania III"][:limit]

    ranker.get_wantlist = fake_get_wantlist
    cache_mod.get_wantlist = fake_get_wantlist

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        cache_dir = root / "cache"
        config = Config(roms_root=root / "ROMs", cache_dir=cache_dir)
        path = cache_mod.cache_path(cache_dir, "nes")
        path.parent.mkdir(parents=True, exist_ok=True)

        expired_payload = {
            "cached_at": (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat(),
            "ttl_hours": 24,
            "console": "nes",
            "titles": ["Old Title"],
        }
        path.write_text(
            json.dumps(expired_payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        assert cache_mod.load_cached(cache_dir, "nes") is None

        titles, from_cache = cache_mod.get_or_fetch_wantlist(_fake_console_entry(), None, config, 5)
        assert from_cache is False
        assert calls["count"] == 1
        assert titles == ["Mega Man 2", "Castlevania III"]

        _write_evidence(
            "cache-expired",
            "\n".join(
                [
                    f"cache_file={path}",
                    f"expired_cached_at={expired_payload['cached_at']}",
                    "load_cached=None",
                    f"from_cache={from_cache}",
                    f"call_count={calls['count']}",
                    f"titles={titles}",
                ]
            ),
        )

    print("OK: expired cache falls back to fetch")


if __name__ == "__main__":
    try:
        main()
    except AssertionError:
        raise SystemExit(1)
