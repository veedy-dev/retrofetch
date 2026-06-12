from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from retrofetch.catalog import CATALOG_SCHEMA_VERSION
from retrofetch.wantlist_cache import (
    CachedWantlist,
    cache_path,
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
