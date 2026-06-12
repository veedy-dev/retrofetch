from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


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


def test_all_class_abc_consoles_have_minerva_paths_or_documented_exception() -> None:
    consoles = _load_consoles()
    abc = [entry for entry in consoles if entry.get("class") in ("A", "B", "C")]
    documented_unavailable = {"switch"}
    missing = {entry["shortname"] for entry in abc if not entry.get("minerva_path")}

    assert len(abc) == 89
    assert missing == documented_unavailable


def test_regional_aliases_use_base_minerva_paths() -> None:
    consoles = {entry["shortname"]: entry for entry in _load_consoles()}

    assert consoles["megacdjp"]["minerva_path"] == consoles["megacd"]["minerva_path"]
    assert consoles["megadrivejp"]["minerva_path"] == consoles["megadrive"]["minerva_path"]
    assert consoles["neogeocdjp"]["minerva_path"] == consoles["neogeocd"]["minerva_path"]
    assert consoles["saturnjp"]["minerva_path"] == consoles["saturn"]["minerva_path"]
    assert consoles["sega32xjp"]["minerva_path"] == consoles["sega32x"]["minerva_path"]
    assert consoles["sega32xna"]["minerva_path"] == consoles["sega32x"]["minerva_path"]
    assert consoles["snesna"]["minerva_path"] == consoles["snes"]["minerva_path"]
