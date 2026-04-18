"""Bug-fix QA: empty ranker result does NOT create a cache file."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

REPO_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = REPO_ROOT / ".sisyphus" / "evidence" / "ux-bug1-empty-no-cache.txt"

from retrofetch.config import Config
import retrofetch.ranker as ranker_mod
import retrofetch.wantlist_cache as cache_mod
from retrofetch.wantlist_cache import cache_path, get_or_fetch_wantlist, load_cached


def main() -> int:
    orig_ranker = ranker_mod.get_wantlist
    try:
        # Scenario 1: empty result -> NO cache file written
        ranker_mod.get_wantlist = lambda **_: []
        with tempfile.TemporaryDirectory() as td:
            cfg_dir = Path(td)
            cache_dir = cfg_dir / "cache"
            config = Config(roms_root=cfg_dir / "ROMs", cache_dir=cache_dir)
            entry = {"shortname": "testcon", "class": "A"}

            titles, from_cache = get_or_fetch_wantlist(
                console_entry=entry, overrides=None, config=config, limit=10,
            )
            assert titles == [], f"expected empty titles, got {titles}"
            assert from_cache is False, f"expected from_cache=False, got {from_cache}"

            # Critical assertion: NO file should exist
            path = cache_path(cache_dir, "testcon")
            assert not path.exists(), f"cache file should NOT exist for empty result: {path}"
            assert load_cached(cache_dir, "testcon") is None

        # Scenario 2: non-empty still caches
        ranker_mod.get_wantlist = lambda **_: ["Alpha", "Beta"]
        with tempfile.TemporaryDirectory() as td:
            cfg_dir = Path(td)
            cache_dir = cfg_dir / "cache"
            config = Config(roms_root=cfg_dir / "ROMs", cache_dir=cache_dir)
            entry = {"shortname": "testcon", "class": "A"}

            titles, from_cache = get_or_fetch_wantlist(
                console_entry=entry, overrides=None, config=config, limit=10,
            )
            assert titles == ["Alpha", "Beta"], f"expected titles, got {titles}"
            assert from_cache is False
            path = cache_path(cache_dir, "testcon")
            assert path.exists(), "non-empty result should have been cached"

            # Second call must be cache hit
            titles2, from_cache2 = get_or_fetch_wantlist(
                console_entry=entry, overrides=None, config=config, limit=10,
            )
            assert titles2 == ["Alpha", "Beta"]
            assert from_cache2 is True

    finally:
        ranker_mod.get_wantlist = orig_ranker

    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text(
        "status=PASS\nempty_result_no_cache=OK\nnonempty_result_cached=OK\n",
        encoding="utf-8",
    )
    print("OK: empty result skips cache; non-empty result persists")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"FAIL: {exc!r}", file=sys.stderr)
        import traceback; traceback.print_exc()
        raise SystemExit(1)
