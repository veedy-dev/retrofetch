from __future__ import annotations

from pathlib import Path

from retrofetch.config import Config, ConsoleOverride
from retrofetch.ranker import get_wantlist, resolve_download_set
from retrofetch.sources import SourceUnavailable
from retrofetch.sources.romsfun import RomsfunSource


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


def test_romsfun_limit_zero_is_unlimited(monkeypatch) -> None:
    source = RomsfunSource(
        {"romsfun_slug": "gba"}, base_url="https://example.invalid/roms/"
    )
    monkeypatch.setattr(
        source,
        "_get",
        lambda _url: """
            <a href="/roms/gba/alpha">Alpha</a>
            <a href="/roms/gba/bravo">Bravo</a>
        """,
    )

    assert source.list_popular(limit=0) == ["Alpha", "Bravo"]


def test_ranker_stops_on_empty_configured_minerva_but_falls_back_on_failure(
    monkeypatch,
) -> None:
    factories = __import__(
        "retrofetch.ranker", fromlist=["_SOURCE_FACTORIES"]
    )._SOURCE_FACTORIES
    fallback_calls: list[str] = []

    class _EmptyMinerva(_FakeSource):
        def list_popular(
            self, limit: int, region_priority: list[str] | None = None
        ) -> list[str]:
            return []

    class _FailedMinerva(_FakeSource):
        def list_popular(
            self, limit: int, region_priority: list[str] | None = None
        ) -> list[str]:
            raise SourceUnavailable("all Minerva roots failed")

    class _Fallback(_FakeSource):
        def list_popular(
            self, limit: int, region_priority: list[str] | None = None
        ) -> list[str]:
            fallback_calls.append("called")
            return ["Fallback"]

    monkeypatch.setitem(factories, "minerva_http", _EmptyMinerva)
    monkeypatch.setitem(factories, "fallback", _Fallback)
    config = Config(
        roms_root=Path("ROMs"),
        ranking_sources_by_class={"A": ["minerva_http", "fallback"]},
    )
    console: dict[str, object] = {
        "shortname": "test",
        "class": "A",
        "minerva_path": "Redump/Test",
    }

    assert get_wantlist(console, None, config, 10) == []
    assert fallback_calls == []

    monkeypatch.setitem(factories, "minerva_http", _FailedMinerva)
    assert get_wantlist(console, None, config, 10) == ["Fallback"]
    assert fallback_calls == ["called"]
