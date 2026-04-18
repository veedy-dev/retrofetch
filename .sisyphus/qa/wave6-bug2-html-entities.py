"""Bug-fix QA: wantlist_cache decodes HTML entities before returning/caching."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

REPO_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = REPO_ROOT / ".sisyphus" / "evidence" / "ux-bug2-html-entities.txt"

from retrofetch.config import Config
import retrofetch.ranker as ranker_mod
from retrofetch.wantlist_cache import cache_path, get_or_fetch_wantlist


def main() -> int:
    raw = [
        "Sonic 3 &#038; Knuckles",
        "Ghouls &#8216;n Ghosts &#8211; Restoration",
        "Beryl&#8217;s Revenge",
        "Normal Title",
    ]
    orig = ranker_mod.get_wantlist
    ranker_mod.get_wantlist = lambda **_: list(raw)
    try:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            cache_dir = td_path / "cache"
            config = Config(roms_root=td_path / "ROMs", cache_dir=cache_dir)
            entry = {"shortname": "nes", "class": "A", "display_name": "NES"}

            titles, from_cache = get_or_fetch_wantlist(
                console_entry=entry,
                overrides=None,
                config=config,
                limit=10,
            )
            assert from_cache is False
            assert any("Sonic 3 & Knuckles" in t for t in titles), titles
            assert any("Beryl" in t and "\u2019" in t for t in titles), titles
            assert any("Ghouls" in t and "\u2018" in t and "\u2013" in t for t in titles), titles
            for t in titles:
                assert "&#" not in t, f"lingering entity in {t!r}"

            path = cache_path(cache_dir, "nes")
            assert path.exists()
            data = json.loads(path.read_text(encoding="utf-8"))
            cached_titles = data["titles"]
            for t in cached_titles:
                assert "&#" not in t, f"cache contains entity {t!r}"
    finally:
        ranker_mod.get_wantlist = orig

    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text(
        "status=PASS\ndecoded_return=OK\ndecoded_cache=OK\n", encoding="utf-8"
    )
    print("OK: wantlist_cache decodes HTML entities (return + persist)")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"FAIL: {exc!r}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        raise SystemExit(1)
