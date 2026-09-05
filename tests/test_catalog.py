from __future__ import annotations

import pytest

from retrofetch.catalog import (
    CATALOG_SCHEMA_VERSION,
    CatalogFile,
    build_catalog,
    parse_nointro_name,
)


@pytest.mark.parametrize(
    ("filename", "title", "regions", "revision", "disc", "tags", "unlicensed"),
    [
        ("Super Mario Bros. (USA).zip", "Super Mario Bros.", ["USA"], None, None, [], False),
        ("Chrono Trigger (Japan).zip", "Chrono Trigger", ["Japan"], None, None, [], False),
        ("Game (USA, Europe).zip", "Game", ["USA", "Europe"], None, None, [], False),
        ("Game (World).7z", "Game", ["World"], None, None, [], False),
        ("Legend of Zelda, The (USA) (Rev 1).zip", "Legend of Zelda, The", ["USA"], "1", None, [], False),
        ("Racing Game (Europe) (v1.1).zip", "Racing Game", ["Europe"], "v1.1", None, [], False),
        ("RPG (USA) (Disc 2).zip", "RPG", ["USA"], None, 2, [], False),
        ("RPG (USA) (Disk 3).zip", "RPG", ["USA"], None, 3, [], False),
        ("Game (USA) (En,Fr,De).zip", "Game", ["USA"], None, None, ["En,Fr,De"], False),
        ("Game (USA) [T-En by Fans].zip", "Game", ["USA"], None, None, ["T-En by Fans"], False),
        ("Game (USA) [b].zip", "Game", ["USA"], None, None, ["b"], False),
        ("Prototype Game (USA) (Proto).zip", "Prototype Game", ["USA"], None, None, ["Proto"], True),
        ("Demo Game (USA) (Demo).zip", "Demo Game", ["USA"], None, None, ["Demo"], True),
        ("Kiosk Game (USA) (Kiosk).zip", "Kiosk Game", ["USA"], None, None, ["Kiosk"], True),
        ("Pirate Game (USA) (Pirate).zip", "Pirate Game", ["USA"], None, None, ["Pirate"], True),
        ("Aftermarket Game (USA) (Aftermarket).zip", "Aftermarket Game", ["USA"], None, None, ["Aftermarket"], True),
        ("Pokémon Édition (France).zip", "Pokémon Édition", ["France"], None, None, [], False),
        ("Title, The (Australia).zip", "Title, The", ["Australia"], None, None, [], False),
        ("No Tags.iso", "No Tags", [], None, None, [], False),
        ("Arcade Game (USA) (Sample).zip", "Arcade Game", ["USA"], None, None, ["Sample"], True),
    ],
)
def test_parse_nointro_name_cases(
    filename: str,
    title: str,
    regions: list[str],
    revision: str | None,
    disc: int | None,
    tags: list[str],
    unlicensed: bool,
) -> None:
    parsed = parse_nointro_name(filename)

    assert parsed.title == title
    assert parsed.regions == regions
    assert parsed.revision == revision
    assert parsed.disc == disc
    assert parsed.tags == tags
    assert parsed.is_unlicensed_variant is unlicensed


def test_catalog_schema_version_is_wave_one_value() -> None:
    assert CATALOG_SCHEMA_VERSION == 4


def test_build_catalog_empty_input() -> None:
    assert build_catalog([], region_priority=["USA"], exclude_keywords=[]) == []


def test_build_catalog_region_priority_and_japan_only_survives() -> None:
    files = [
        CatalogFile("Only Japan (Japan).zip", "https://example/jp", None),
        CatalogFile("Dual Release (Europe).zip", "https://example/eu", None),
        CatalogFile("Dual Release (USA).zip", "https://example/us", None),
    ]

    entries = build_catalog(
        files,
        region_priority=["USA", "World", "Europe", "Japan"],
        exclude_keywords=[],
    )

    by_title = {entry.title: entry for entry in entries}
    assert by_title["Only Japan"].region == "Japan"
    assert by_title["Dual Release"].files[0].filename == "Dual Release (USA).zip"


def test_build_catalog_picks_highest_revision_within_best_region() -> None:
    files = [
        CatalogFile("Game (USA).zip", "https://example/r0", None),
        CatalogFile("Game (USA) (Rev 1).zip", "https://example/r1", None),
        CatalogFile("Game (USA) (Rev 2).zip", "https://example/r2", None),
        CatalogFile("Game (Europe) (Rev 9).zip", "https://example/eu", None),
    ]

    entries = build_catalog(
        files,
        region_priority=["USA", "Europe"],
        exclude_keywords=[],
    )

    assert len(entries) == 1
    assert entries[0].files[0].filename == "Game (USA) (Rev 2).zip"


def test_build_catalog_prefers_base_release_over_platform_variants() -> None:
    files = [
        CatalogFile("Game (USA) (Rev 1) (Virtual Console).zip", "https://example/vc", None),
        CatalogFile("Game (USA) (Rev 1).zip", "https://example/base", None),
    ]

    entries = build_catalog(files, region_priority=["USA"], exclude_keywords=[])

    assert [file.filename for file in entries[0].files] == ["Game (USA) (Rev 1).zip"]


def test_build_catalog_groups_multi_disc_release() -> None:
    files = [
        CatalogFile("Mega RPG (USA) (Disc 3).zip", "https://example/d3", None),
        CatalogFile("Mega RPG (USA) (Disc 1).zip", "https://example/d1", None),
        CatalogFile("Mega RPG (USA) (Disc 2).zip", "https://example/d2", None),
    ]

    entries = build_catalog(files, region_priority=["USA"], exclude_keywords=[])

    assert len(entries) == 1
    assert [file.filename for file in entries[0].files] == [
        "Mega RPG (USA) (Disc 1).zip",
        "Mega RPG (USA) (Disc 2).zip",
        "Mega RPG (USA) (Disc 3).zip",
    ]


def test_build_catalog_excludes_keywords_and_bios() -> None:
    files = [
        CatalogFile("Good Game (USA).zip", "https://example/good", None),
        CatalogFile("Bad Game (USA) (Beta).zip", "https://example/beta", None),
        CatalogFile("[BIOS] System (USA).zip", "https://example/bios", None),
    ]

    entries = build_catalog(
        files,
        region_priority=["USA"],
        exclude_keywords=["(Beta)", "(Proto)", "(Demo)", "(Sample)", "(Kiosk)"],
    )

    assert [entry.title for entry in entries] == ["Good Game"]


def test_build_catalog_articles_group_only_key_not_display() -> None:
    files = [
        CatalogFile("Legend, The (USA).zip", "https://example/us", None),
        CatalogFile("The Legend (Europe).zip", "https://example/eu", None),
    ]

    entries = build_catalog(files, region_priority=["USA", "Europe"], exclude_keywords=[])

    assert len(entries) == 1
    assert entries[0].title == "Legend, The"


def test_build_catalog_one_g_one_r_false_returns_ungrouped_entries() -> None:
    files = [
        CatalogFile("Game (USA).zip", "https://example/us", None),
        CatalogFile("Game (Europe).zip", "https://example/eu", None),
    ]

    entries = build_catalog(
        files,
        region_priority=["USA", "Europe"],
        exclude_keywords=[],
        one_g_one_r=False,
    )

    assert [entry.files[0].filename for entry in entries] == [
        "Game (USA).zip",
        "Game (Europe).zip",
    ]
