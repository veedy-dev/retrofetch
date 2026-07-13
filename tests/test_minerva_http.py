from __future__ import annotations

import pytest

from retrofetch.sources import SourceUnavailable
from retrofetch.sources.minerva_http import MinervaHttpSource, effective_minerva_paths


class _FixtureMinerva(MinervaHttpSource):
    def __init__(
        self,
        pages: dict[str, str | SourceUnavailable],
        *,
        minerva_paths: object = None,
    ) -> None:
        console_entry: dict[str, object] = {
            "minerva_path": "Redump/PSP",
            "extensions": [".zip"],
            "exclude_keywords": ["(Beta)"],
        }
        if minerva_paths is not None:
            console_entry["minerva_paths"] = minerva_paths
        super().__init__(
            console_entry,
            base_url="https://minerva.test/browse/",
        )
        self.pages = pages

    def _fetch_text(self, url: str) -> str:
        page = self.pages[url]
        if isinstance(page, SourceUnavailable):
            raise page
        return page


def test_minerva_catalog_parses_rom_links_sizes_and_one_subdir() -> None:
    root = "https://minerva.test/browse/Redump/PSP/"
    subdir = "https://minerva.test/browse/Redump/PSP/Hacks/"
    source = _FixtureMinerva(
        {
            root: """
            <table>
              <tr><td><a href="/rom?name=Redump/PSP/Burnout%20Dominator%20(USA).zip">Burnout Dominator (USA).zip</a></td><td>1.5 GiB</td></tr>
              <tr><td><a href="/rom?name=Redump/PSP/Burnout%20Dominator%20(Europe).zip">Burnout Dominator (Europe).zip</a></td><td>1.4 GiB</td></tr>
              <tr><td><a href="/rom?name=Redump/PSP/Prototype%20(USA)%20(Beta).zip">Prototype (USA) (Beta).zip</a></td><td>7 MiB</td></tr>
              <tr><td><a href="Hacks/">Hacks/</a></td></tr>
            </table>
            """,
            subdir: """
            <ul>
              <li><a href="/rom?name=Redump/PSP/Hacks/Ridge%20Racer%20(World).zip">Ridge Racer (World).zip</a> 700 MiB</li>
            </ul>
            """,
        }
    )

    titles = source.list_popular(limit=0, region_priority=["USA", "World", "Europe"])
    candidate = source.find_url_for_game("Burnout Dominator", ["USA", "Europe"])
    entry = source.get_entry("Burnout Dominator", ["USA", "Europe"])

    assert titles == ["Burnout Dominator", "Ridge Racer"]
    assert candidate is None
    assert entry is not None
    assert entry.files[0].filename == "Burnout Dominator (USA).zip"
    assert entry.files[0].size == 1_610_612_736
    assert entry.files[0].url == (
        "https://minerva.test/rom?name=Redump/PSP/"
        "Burnout%20Dominator%20%28USA%29.zip"
    )


def test_minerva_limit_caps_titles_after_catalog_build() -> None:
    root = "https://minerva.test/browse/Redump/PSP/"
    source = _FixtureMinerva(
        {
            root: """
            <a href="/rom?name=Redump/PSP/A%20Game%20(USA).zip">A Game (USA).zip</a>
            <a href="/rom?name=Redump/PSP/B%20Game%20(USA).zip">B Game (USA).zip</a>
            """
        }
    )

    assert source.list_popular(limit=1, region_priority=["USA"]) == ["A Game"]


def test_minerva_limit_none_and_zero_are_unlimited() -> None:
    root = "https://minerva.test/browse/Redump/PSP/"
    source = _FixtureMinerva(
        {
            root: """
            <a href="/rom?name=Redump/PSP/A%20Game%20(USA).zip">A Game (USA).zip</a>
            <a href="/rom?name=Redump/PSP/B%20Game%20(USA).zip">B Game (USA).zip</a>
            """
        }
    )

    assert source.list_popular(limit=0, region_priority=["USA"]) == ["A Game", "B Game"]
    assert source.list_popular(limit=None, region_priority=["USA"]) == ["A Game", "B Game"]  # type: ignore[arg-type]


def test_minerva_unavailable_bubbles_source_unavailable() -> None:
    class _UnavailableMinerva(_FixtureMinerva):
        def _fetch_text(self, url: str) -> str:
            raise SourceUnavailable("minerva index not found")

    with pytest.raises(SourceUnavailable, match="not found"):
        _UnavailableMinerva({}).list_popular(limit=0, region_priority=["USA"])


def test_minerva_merges_ordered_supplements_and_keeps_first_title_owner() -> None:
    primary = "https://minerva.test/browse/Redump/PSP/"
    achievements = "https://minerva.test/browse/RetroAchievements/PSP/"
    translations = "https://minerva.test/browse/T-En/PSP/"
    source = _FixtureMinerva(
        {
            primary: """
                <a href="/rom?name=Redump/PSP/Alpha%20(USA).zip">Alpha (USA).zip</a>
                <a href="/rom?name=Redump/PSP/Shared%20Game%20(USA).zip">Shared Game (USA).zip</a>
            """,
            achievements: """
                <a href="/rom?name=RetroAchievements/PSP/Bravo%20(USA).zip">Bravo (USA).zip</a>
                <a href="/rom?name=RetroAchievements/PSP/shared%20game%20(USA).zip">shared game (USA).zip</a>
            """,
            translations: """
                <a href="/rom?name=T-En/PSP/Charlie%20(World).zip">Charlie (World).zip</a>
            """,
        },
        minerva_paths=[
            "RetroAchievements/PSP",
            "",
            "  ",
            None,
            7,
            "Redump/PSP",
            "RetroAchievements/PSP",
            "T-En/PSP",
        ],
    )

    assert source.list_popular(0, ["USA", "World"]) == [
        "Alpha",
        "Shared Game",
        "Bravo",
        "Charlie",
    ]
    shared = source.get_entry("shared game", ["USA", "World"])
    bravo = source.get_entry("Bravo", ["USA", "World"])
    assert shared is not None
    assert shared.files[0].url.endswith("Redump/PSP/Shared%20Game%20%28USA%29.zip")
    assert bravo is not None
    assert bravo.files[0].url.endswith(
        "RetroAchievements/PSP/Bravo%20%28USA%29.zip"
    )


def test_minerva_ignores_non_list_supplement_configuration() -> None:
    primary = "https://minerva.test/browse/Redump/PSP/"
    source = _FixtureMinerva(
        {
            primary: '<a href="/rom?name=Redump/PSP/Alpha%20(USA).zip">Alpha (USA).zip</a>'
        },
        minerva_paths="RetroAchievements/PSP",
    )

    assert source.list_popular(0, ["USA"]) == ["Alpha"]


def test_effective_minerva_paths_requires_and_normalizes_primary() -> None:
    invalid_entries = [
        {},
        {"minerva_path": None, "minerva_paths": ["Supplement/PSP"]},
        {"minerva_path": " /// ", "minerva_paths": ["Supplement/PSP"]},
        {"minerva_path": 7, "minerva_paths": ["Supplement/PSP"]},
    ]
    assert all(effective_minerva_paths(entry) == [] for entry in invalid_entries)
    assert effective_minerva_paths(
        {
            "minerva_path": " /Redump/PSP/ ",
            "minerva_paths": [
                "/Redump/PSP/",
                " /RetroAchievements/PSP/ ",
            ],
        }
    ) == ["Redump/PSP", "RetroAchievements/PSP"]


def test_minerva_keeps_primary_multifile_but_omits_supplemental_multifile() -> None:
    primary = "https://minerva.test/browse/Redump/PSP/"
    supplement = "https://minerva.test/browse/T-En/PSP/"
    source = _FixtureMinerva(
        {
            primary: """
                <a href="/rom?name=Redump/PSP/Primary%20Set%20(USA)%20(Disc%201).zip">Primary Set (USA) (Disc 1).zip</a>
                <a href="/rom?name=Redump/PSP/Primary%20Set%20(USA)%20(Disc%202).zip">Primary Set (USA) (Disc 2).zip</a>
            """,
            supplement: """
                <a href="/rom?name=T-En/PSP/Single%20Game%20(World).zip">Single Game (World).zip</a>
                <a href="/rom?name=T-En/PSP/Translated%20Set%20(World)%20(Disc%201).zip">Translated Set (World) (Disc 1).zip</a>
                <a href="/rom?name=T-En/PSP/Translated%20Set%20(World)%20(Disc%202).zip">Translated Set (World) (Disc 2).zip</a>
            """,
        },
        minerva_paths=["T-En/PSP"],
    )

    assert source.list_popular(0, ["USA", "World"]) == [
        "Primary Set",
        "Single Game",
    ]
    primary_entry = source.get_entry("Primary Set", ["USA", "World"])
    assert primary_entry is not None
    assert len(primary_entry.files) == 2
    assert source.get_entry("Translated Set", ["USA", "World"]) is None


def test_minerva_isolates_root_failures_and_distinguishes_empty_catalogs() -> None:
    primary = "https://minerva.test/browse/Redump/PSP/"
    supplement = "https://minerva.test/browse/RetroAchievements/PSP/"
    failed = SourceUnavailable("supplement unavailable")

    primary_survives = _FixtureMinerva(
        {
            primary: '<a href="/rom?name=Redump/PSP/Alpha%20(USA).zip">Alpha (USA).zip</a>',
            supplement: failed,
        },
        minerva_paths=["RetroAchievements/PSP"],
    )
    assert primary_survives.list_popular(0, ["USA"]) == ["Alpha"]

    supplement_after_empty_primary = _FixtureMinerva(
        {
            primary: "<p>empty</p>",
            supplement: '<a href="/rom?name=RetroAchievements/PSP/Bravo%20(USA).zip">Bravo (USA).zip</a>',
        },
        minerva_paths=["RetroAchievements/PSP"],
    )
    assert supplement_after_empty_primary.list_popular(0, ["USA"]) == ["Bravo"]

    all_empty = _FixtureMinerva(
        {primary: "<p>empty</p>", supplement: "<p>also empty</p>"},
        minerva_paths=["RetroAchievements/PSP"],
    )
    assert all_empty.list_popular(0, ["USA"]) == []

    all_failed = _FixtureMinerva(
        {
            primary: SourceUnavailable("primary unavailable"),
            supplement: failed,
        },
        minerva_paths=["RetroAchievements/PSP"],
    )
    with pytest.raises(SourceUnavailable):
        all_failed.list_popular(0, ["USA"])


def test_minerva_applies_limit_after_merged_deduplication() -> None:
    primary = "https://minerva.test/browse/Redump/PSP/"
    supplement = "https://minerva.test/browse/RetroAchievements/PSP/"
    source = _FixtureMinerva(
        {
            primary: '<a href="/rom?name=Redump/PSP/Alpha%20(USA).zip">Alpha (USA).zip</a>',
            supplement: """
                <a href="/rom?name=RetroAchievements/PSP/Alpha%20(USA).zip">Alpha (USA).zip</a>
                <a href="/rom?name=RetroAchievements/PSP/Bravo%20(USA).zip">Bravo (USA).zip</a>
                <a href="/rom?name=RetroAchievements/PSP/Charlie%20(USA).zip">Charlie (USA).zip</a>
            """,
        },
        minerva_paths=["RetroAchievements/PSP"],
    )

    assert source.list_popular(0, ["USA"]) == ["Alpha", "Bravo", "Charlie"]
    assert source.list_popular(2, ["USA"]) == ["Alpha", "Bravo"]
