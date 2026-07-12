from __future__ import annotations

from pathlib import Path

from retrofetch.config import Config, ConsoleOverride
from retrofetch.ranker import get_wantlist, resolve_download_set


class _FakeSource:
    def __init__(self, entry: dict[str, object]) -> None:
        self.entry = entry

    def list_popular(
        self, limit: int, region_priority: list[str] | None = None
    ) -> list[str]:
        assert self.entry["exclude_keywords"] == ["(Beta)"]
        assert region_priority == ["Europe", "USA"]
        return ["Alpha", "Bravo", "Charlie"]


def test_get_wantlist_returns_raw_catalog_without_include_exclude(monkeypatch) -> None:
    monkeypatch.setitem(
        __import__("retrofetch.ranker", fromlist=["_SOURCE_FACTORIES"])._SOURCE_FACTORIES,
        "fake",
        _FakeSource,
    )
    config = Config(
        roms_root=Path("ROMs"),
        ranking_sources_by_class={"A": ["fake"]},
        exclude_keywords=["(Beta)"],
    )
    override = ConsoleOverride(
        include=["Selected"],
        exclude=["Bravo"],
        region_priority=["Europe", "USA"],
    )

    assert get_wantlist({"shortname": "x", "class": "A"}, override, config, 10) == [
        "Alpha",
        "Bravo",
        "Charlie",
    ]


def test_resolve_download_set_include_is_exact_ordered_selection(caplog) -> None:
    override = ConsoleOverride(
        include=["Charlie", "Missing", "Bravo", "Charlie"],
        exclude=["Bravo"],
    )

    result = resolve_download_set(["Alpha", "Bravo", "Charlie"], override, limit=1)

    assert result == ["Charlie", "Missing"]
    assert "included title not found" in caplog.text


def test_resolve_download_set_without_include_applies_exclude_and_limit() -> None:
    override = ConsoleOverride(exclude=["Bravo"])

    result = resolve_download_set(["Alpha", "Bravo", "Charlie"], override, limit=2)

    assert result == ["Alpha", "Charlie"]


def test_resolve_download_set_limit_zero_is_unlimited() -> None:
    assert resolve_download_set(["A", "B", "C"], None, limit=0) == ["A", "B", "C"]
