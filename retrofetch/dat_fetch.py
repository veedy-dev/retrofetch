"""DAT acquisition and bundled snapshot."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def find_dat_for_console(
    shortname: str,
    consoles_yml: dict[str, Any],
    dats_dir: Path = Path("dats"),
) -> Path | None:
    consoles = consoles_yml.get("consoles", [])
    entry = next((c for c in consoles if c.get("shortname") == shortname), None)
    if entry is None:
        return None
    if entry.get("class") not in ("A", "B", "C"):
        return None
    parent_short = entry.get("region_alias_of")
    if parent_short and not entry.get("dat_system"):
        return find_dat_for_console(parent_short, consoles_yml, dats_dir)
    subdir = "redump" if entry.get("cd_based") else "no-intro"
    candidate = Path(dats_dir) / subdir / f"{shortname}.dat"
    if candidate.exists():
        return candidate
    dat_system = entry.get("dat_system")
    if dat_system:
        alt = Path(dats_dir) / subdir / f"{dat_system}.dat"
        if alt.exists():
            return alt
    return None


def bootstrap_dats(dats_dir: Path = Path("dats")) -> None:
    dats_dir = Path(dats_dir)
    dats_dir.mkdir(parents=True, exist_ok=True)
    (dats_dir / "no-intro").mkdir(exist_ok=True)
    (dats_dir / "redump").mkdir(exist_ok=True)
