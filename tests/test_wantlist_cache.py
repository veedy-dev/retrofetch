from __future__ import annotations

import asyncio
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from retrofetch.catalog import CATALOG_SCHEMA_VERSION
from retrofetch.config import Config, ConsoleOverride
from retrofetch.tui.app import RetrofetchApp
from retrofetch.wantlist_cache import (
    CachedWantlist,
    cache_path,
    get_or_fetch_wantlist,
    invalidate,
    is_recently_empty,
    load_cached,
    mark_empty,
    save_cached,
)


def test_legacy_cache_is_ignored_and_deleted(scratch_path) -> None:
    path = cache_path(scratch_path, "psp")
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "cached_at": datetime.now(timezone.utc).isoformat(),
                "ttl_hours": 24,
                "console": "psp",
                "titles": ["Old Game"],
            }
        ),
        encoding="utf-8",
    )

    assert load_cached(scratch_path, "psp") is None
    assert not path.exists()


def test_current_cache_roundtrips(scratch_path) -> None:
    entry = CachedWantlist(
        console="psp",
        titles=["Game A", "Game B"],
        cached_at=datetime.now(timezone.utc),
        ttl_hours=24,
    )

    save_cached(scratch_path, entry)
    raw = json.loads(cache_path(scratch_path, "psp").read_text(encoding="utf-8"))
    loaded = load_cached(scratch_path, "psp")

    assert raw["schema_version"] == CATALOG_SCHEMA_VERSION
    assert loaded is not None
    assert loaded.titles == ["Game A", "Game B"]


def test_force_refresh_replaces_fresh_cache(monkeypatch, scratch_path) -> None:
    save_cached(
        scratch_path,
        CachedWantlist(
            console="psp",
            titles=["Old Game"],
            cached_at=datetime.now(timezone.utc),
            ttl_hours=24,
        ),
    )
    monkeypatch.setattr(
        "retrofetch.ranker.get_wantlist", lambda **_kwargs: ["New Game"]
    )
    config = Config(roms_root=scratch_path / "ROMs", cache_dir=scratch_path)

    titles, from_cache = get_or_fetch_wantlist(
        {"shortname": "psp", "class": "B"},
        None,
        config,
        0,
        force_refresh=True,
    )

    assert titles == ["New Game"]
    assert from_cache is False
    loaded = load_cached(scratch_path, "psp")
    assert loaded is not None
    assert loaded.titles == ["New Game"]


def test_first_fetch_and_cache_hit_have_identical_full_projection(
    monkeypatch, scratch_path
) -> None:
    raw_titles = ["Tom &amp;amp; Jerry", "Excluded"] + [
        f"Game {index:04d}" for index in range(1001)
    ]
    monkeypatch.setattr(
        "retrofetch.ranker.get_wantlist", lambda **kwargs: raw_titles
    )
    config = Config(
        roms_root=scratch_path / "ROMs",
        cache_dir=scratch_path / ".cache",
    )
    override = ConsoleOverride(exclude=["Excluded"])
    entry: dict[str, object] = {"shortname": "psx", "class": "B"}

    first, first_from_cache = get_or_fetch_wantlist(entry, override, config, limit=0)
    revisit, revisit_from_cache = get_or_fetch_wantlist(
        entry, override, config, limit=0
    )

    assert first_from_cache is False
    assert revisit_from_cache is True
    assert first == revisit
    assert first[0] == "Tom &amp; Jerry"
    assert "Excluded" not in first
    assert len(first) == 1002


def test_concurrent_cache_misses_share_one_fetch(monkeypatch, scratch_path) -> None:
    started = threading.Event()
    release = threading.Event()
    second_started = threading.Event()
    calls = 0

    def fetch(**_kwargs):
        nonlocal calls
        calls += 1
        started.set()
        assert release.wait(2)
        return ["Game"]

    monkeypatch.setattr("retrofetch.ranker.get_wantlist", fetch)
    config = Config(roms_root=scratch_path / "ROMs", cache_dir=scratch_path)
    entry: dict[str, object] = {"shortname": "psp", "class": "B"}

    def fetch_second():
        second_started.set()
        return get_or_fetch_wantlist(entry, None, config, 0)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(get_or_fetch_wantlist, entry, None, config, 0)
        assert started.wait(1)
        second = pool.submit(fetch_second)
        assert second_started.wait(1)
        release.set()
        results = [first.result(), second.result()]

    assert calls == 1
    assert sorted(from_cache for _titles, from_cache in results) == [False, True]


def test_different_consoles_fetch_independently(monkeypatch, scratch_path) -> None:
    psp_started = threading.Event()
    release_psp = threading.Event()

    def fetch(*, console_entry, **_kwargs):
        shortname = console_entry["shortname"]
        if shortname == "psp":
            psp_started.set()
            assert release_psp.wait(2)
        return [str(shortname)]

    monkeypatch.setattr("retrofetch.ranker.get_wantlist", fetch)
    config = Config(roms_root=scratch_path / "ROMs", cache_dir=scratch_path)

    with ThreadPoolExecutor(max_workers=2) as pool:
        psp = pool.submit(
            get_or_fetch_wantlist,
            {"shortname": "psp", "class": "B"},
            None,
            config,
            0,
        )
        assert psp_started.wait(1)
        ps2 = pool.submit(
            get_or_fetch_wantlist,
            {"shortname": "ps2", "class": "B"},
            None,
            config,
            0,
        )
        try:
            assert ps2.result(timeout=1)[0] == ["ps2"]
        finally:
            release_psp.set()
        assert psp.result()[0] == ["psp"]


def test_invalidation_prevents_an_older_fetch_from_restoring_cache(
    monkeypatch, scratch_path
) -> None:
    first_started = threading.Event()
    release_first = threading.Event()
    calls = 0

    def fetch(**_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            first_started.set()
            assert release_first.wait(2)
            return ["Old Game"]
        return ["New Game"]

    monkeypatch.setattr("retrofetch.ranker.get_wantlist", fetch)
    config = Config(roms_root=scratch_path / "ROMs", cache_dir=scratch_path)
    entry: dict[str, object] = {"shortname": "psp", "class": "B"}

    with ThreadPoolExecutor(max_workers=2) as pool:
        old = pool.submit(get_or_fetch_wantlist, entry, None, config, 0)
        assert first_started.wait(1)
        invalidate(scratch_path, "psp")
        new = pool.submit(get_or_fetch_wantlist, entry, None, config, 0)
        release_first.set()
        assert old.result()[0] == ["Old Game"]
        assert new.result()[0] == ["New Game"]

    cached = load_cached(scratch_path, "psp")
    assert calls == 2
    assert cached is not None
    assert cached.titles == ["New Game"]


def test_corrupt_cache_is_miss_and_deleted(scratch_path) -> None:
    path = cache_path(scratch_path, "psp")
    path.parent.mkdir(parents=True)
    path.write_text("NOT JSON{{{", encoding="utf-8")

    assert load_cached(scratch_path, "psp") is None
    assert not path.exists()


def test_expired_cache_is_miss_and_deleted(scratch_path) -> None:
    entry = CachedWantlist(
        console="psp",
        titles=["Game A"],
        cached_at=datetime.now(timezone.utc) - timedelta(hours=25),
        ttl_hours=24,
    )
    save_cached(scratch_path, entry)

    assert load_cached(scratch_path, "psp") is None
    assert not cache_path(scratch_path, "psp").exists()


def test_empty_marker_is_versioned(scratch_path) -> None:
    mark_empty(scratch_path, "psp")
    marker = scratch_path / "empty_marks" / "psp.json"
    raw = json.loads(marker.read_text(encoding="utf-8"))

    assert raw["schema_version"] == CATALOG_SCHEMA_VERSION
    assert is_recently_empty(scratch_path, "psp") is True


def test_invalidate_clears_marker_without_cached_wantlist(scratch_path) -> None:
    mark_empty(scratch_path, "psp")

    assert not cache_path(scratch_path, "psp").exists()
    assert is_recently_empty(scratch_path, "psp") is True

    invalidate(scratch_path, "psp")

    assert is_recently_empty(scratch_path, "psp") is False


def test_legacy_empty_marker_is_ignored_and_deleted(scratch_path) -> None:
    marker = scratch_path / "empty_marks" / "psp.json"
    marker.parent.mkdir(parents=True)
    marker.write_text(
        json.dumps(
            {
                "recorded_at": datetime.now(timezone.utc).isoformat(),
                "ttl_hours": 2,
                "console": "psp",
            }
        ),
        encoding="utf-8",
    )

    assert is_recently_empty(scratch_path, "psp") is False
    assert not marker.exists()


def test_tui_launch_keeps_valid_cache_and_resets_session_selection(
    monkeypatch, scratch_path
) -> None:
    monkeypatch.chdir(scratch_path)
    cached = CachedWantlist(
        console="psp",
        titles=["Old Game"],
        cached_at=datetime.now(timezone.utc),
        ttl_hours=24,
    )
    save_cached(scratch_path / ".cache", cached)
    state_path = scratch_path / "ROMs" / "psp" / ".retrofetch-state.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text('{"status":"downloading"}', encoding="utf-8")
    app = RetrofetchApp(
        config=Config(
            roms_root=scratch_path / "ROMs", cache_dir=scratch_path / ".cache"
        ),
        config_path=Path("config.yml"),
        consoles_yml={"consoles": []},
        overrides={
            "psp": ConsoleOverride(
                include=["Old Choice"],
                exclude=["Other Choice"],
                limit=12,
                region_priority=["Japan"],
            )
        },
    )

    async def run() -> None:
        async with app.run_test():
            loaded = load_cached(scratch_path / ".cache", "psp")
            assert loaded is not None
            assert loaded.titles == ["Old Game"]
            assert app.overrides["psp"].include == []
            assert app.overrides["psp"].exclude == []
            assert app.overrides["psp"].limit == 12
            assert app.overrides["psp"].region_priority == ["Japan"]

    asyncio.run(run())
    assert state_path.read_text(encoding="utf-8") == '{"status":"downloading"}'
