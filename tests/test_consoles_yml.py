from __future__ import annotations

import os
from pathlib import Path
import posixpath
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
import yaml

from retrofetch.catalog import build_catalog
from retrofetch.sources.minerva_http import MinervaHttpSource
from retrofetch.sources.minerva_torrent import (
    MinervaTorrentSource,
    _parse_torrent_metadata,
    _safe_path,
)
from retrofetch.tui.screens.home import HomeScreen


def _load_consoles() -> list[dict[str, Any]]:
    raw = yaml.safe_load(Path("consoles.yml").read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    consoles = raw["consoles"]
    assert isinstance(consoles, list)
    return consoles


def test_console_schema_sanity() -> None:
    consoles = _load_consoles()
    shortnames: set[str] = set()
    for entry in consoles:
        shortname = entry.get("shortname")
        assert isinstance(shortname, str) and shortname
        assert shortname not in shortnames
        shortnames.add(shortname)
        assert entry.get("class") in set("ABCDEF")
        extensions = entry.get("extensions")
        assert isinstance(extensions, list), shortname
        assert all(isinstance(ext, str) and ext.startswith(".") for ext in extensions)
        minerva_path = entry.get("minerva_path")
        assert minerva_path is None or isinstance(minerva_path, str), shortname
        if "minerva_paths" not in entry:
            continue
        minerva_paths = entry["minerva_paths"]
        assert isinstance(minerva_paths, list), shortname
        assert all(isinstance(path, str) and path.strip() == path and path for path in minerva_paths), shortname
        assert len(minerva_paths) == len(set(minerva_paths)), shortname
        assert minerva_path not in minerva_paths, shortname


def test_all_class_abc_consoles_have_minerva_paths_or_documented_exception() -> None:
    consoles = _load_consoles()
    abc = [entry for entry in consoles if entry.get("class") in ("A", "B", "C")]
    documented_unavailable = {"switch"}
    missing = {entry["shortname"] for entry in abc if not entry.get("minerva_path")}

    assert len(abc) == 89
    assert missing == documented_unavailable
    assert sum(HomeScreen._is_available(entry) for entry in consoles) == 89


def test_regional_aliases_use_base_minerva_paths() -> None:
    consoles = {entry["shortname"]: entry for entry in _load_consoles()}

    assert consoles["megacdjp"]["minerva_path"] == consoles["megacd"]["minerva_path"]
    assert consoles["megadrivejp"]["minerva_path"] == consoles["megadrive"]["minerva_path"]
    assert consoles["neogeocdjp"]["minerva_path"] == consoles["neogeocd"]["minerva_path"]
    assert consoles["saturnjp"]["minerva_path"] == consoles["saturn"]["minerva_path"]
    assert consoles["sega32xjp"]["minerva_path"] == consoles["sega32x"]["minerva_path"]
    assert consoles["sega32xna"]["minerva_path"] == consoles["sega32x"]["minerva_path"]
    assert consoles["snesna"]["minerva_path"] == consoles["snes"]["minerva_path"]


def test_verified_sample_minerva_supplement_paths_are_exact() -> None:
    consoles = {entry["shortname"]: entry for entry in _load_consoles()}
    expected = {
        "gba": {
            "RetroAchievements/RA - Nintendo Game Boy Advance",
            "T-En Collection/Nintendo - Game Boy Advance [T-En] Collection",
        },
        "psx": {
            "RetroAchievements/RA - Sony Playstation",
            "T-En Collection/Sony - PlayStation [T-En] Collection",
        },
        "gc": {
            "RetroAchievements/RA - Nintendo GameCube",
            "T-En Collection/Nintendo - GameCube [T-En] Collection",
        },
        "3do": {
            "RetroAchievements/RA - 3DO Interactive Multiplayer",
            "T-En Collection/Panasonic - 3DO Interactive Multiplayer [T-En] Collection",
        },
    }

    for shortname, paths in expected.items():
        assert set(consoles[shortname].get("minerva_paths") or []) == paths


def test_minerva_supplement_mapping_scope_is_frozen() -> None:
    consoles = _load_consoles()
    abc_with_supplements = [
        entry
        for entry in consoles
        if entry.get("class") in ("A", "B", "C") and entry.get("minerva_paths")
    ]

    assert len(abc_with_supplements) == 59
    assert sum(len(entry["minerva_paths"]) for entry in abc_with_supplements) == 81
    assert all(
        entry["minerva_path"] not in entry["minerva_paths"]
        and len(entry["minerva_paths"]) == len(set(entry["minerva_paths"]))
        for entry in abc_with_supplements
    )
    psp = next(entry for entry in consoles if entry["shortname"] == "psp")
    assert "minerva_paths" not in psp


def test_minerva_supplements_do_not_activate_class_def_consoles() -> None:
    supplements = [
        entry["shortname"]
        for entry in _load_consoles()
        if entry.get("class") in ("D", "E", "F") and entry.get("minerva_paths")
    ]

    assert supplements == []


@pytest.mark.skipif(
    os.getenv("RETROFETCH_LIVE_MINERVA_AUDIT") != "1",
    reason="set RETROFETCH_LIVE_MINERVA_AUDIT=1 for the release audit",
)
def test_live_minerva_collections_match_browse_and_torrent_roots() -> None:
    for console in _load_consoles():
        roots = [console.get("minerva_path"), *(console.get("minerva_paths") or [])]
        for root in (value for value in roots if isinstance(value, str) and value):
            root_entry = {**console, "minerva_path": root}
            browse = MinervaHttpSource(root_entry)
            index_url = browse._build_index_url()
            assert index_url is not None
            files = browse._list_catalog_files(index_url)
            assert files, f"{console['shortname']}: empty browse leaf {root}"

            catalog = build_catalog(
                files,
                region_priority=["USA", "World", "Europe", "Japan"],
                exclude_keywords=list(console.get("exclude_keywords") or []),
            )
            multi_file_titles = sum(len(entry.files) > 1 for entry in catalog)

            torrent = MinervaTorrentSource(root_entry)
            torrent_url = torrent._collection_torrent_url()
            assert torrent_url is not None
            metadata = _parse_torrent_metadata(torrent._fetch_torrent_bytes(torrent_url))
            torrent_paths = {item.path for item in metadata.files}
            suffixes = sorted(
                {posixpath.splitext(item.path)[1].lower() for item in metadata.files}
            )
            representative_path = None
            for file in files:
                names = parse_qs(urlsplit(file.url).query).get("name") or []
                browse_path = _safe_path(names[0]) if len(names) == 1 else None
                if browse_path is not None and browse_path in torrent_paths:
                    representative_path = browse_path
                    break
            assert representative_path is not None, (
                f"{console['shortname']}: no browse path exists in {root} torrent"
            )
            print(
                console["shortname"],
                root,
                f"files={len(files)}",
                f"titles={len(catalog)}",
                f"multi={multi_file_titles}",
                f"types={','.join(suffixes)}",
            )
