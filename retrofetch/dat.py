"""DAT parser (Logiqx XML) and hash verifier."""

from __future__ import annotations

import hashlib
import re
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET


@dataclass
class Rom:
    name: str
    size: int
    crc32: str | None = None
    md5: str | None = None
    sha1: str | None = None


@dataclass
class GameEntry:
    name: str
    description: str
    category: str | None
    roms: list[Rom] = field(default_factory=list)


@dataclass
class DatEntry:
    games: list[GameEntry] = field(default_factory=list)

    def by_name(self, name: str) -> GameEntry | None:
        for g in self.games:
            if g.name == name:
                return g
        return None


@dataclass
class VerifyResult:
    matched: bool
    reason: str | None
    computed_sha1: str
    computed_crc32: str
    computed_md5: str


def parse_dat(dat_path: Path) -> DatEntry:
    games: list[GameEntry] = []
    for _event, elem in ET.iterparse(str(dat_path), events=("end",)):
        if elem.tag == "game":
            roms: list[Rom] = []
            for rom_el in elem.findall("rom"):
                size_raw = rom_el.get("size", "0")
                try:
                    size = int(size_raw)
                except ValueError:
                    size = 0
                roms.append(
                    Rom(
                        name=rom_el.get("name", ""),
                        size=size,
                        crc32=(rom_el.get("crc") or None),
                        md5=(rom_el.get("md5") or None),
                        sha1=(rom_el.get("sha1") or None),
                    )
                )
            desc_el = elem.find("description")
            description = (
                desc_el.text
                if desc_el is not None and desc_el.text
                else elem.get("name", "")
            )
            games.append(
                GameEntry(
                    name=elem.get("name", ""),
                    description=description,
                    category=elem.get("category"),
                    roms=roms,
                )
            )
            elem.clear()
    return DatEntry(games=games)


def _compute_hashes(file: Path) -> tuple[str, str, str]:
    sha1 = hashlib.sha1()
    md5 = hashlib.md5()
    crc = 0
    with open(file, "rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            sha1.update(chunk)
            md5.update(chunk)
            crc = zlib.crc32(chunk, crc)
    return sha1.hexdigest(), md5.hexdigest(), f"{crc & 0xFFFFFFFF:08x}"


def verify_file(file: Path, expected: Rom) -> VerifyResult:
    if not file.exists():
        return VerifyResult(False, f"file not found: {file}", "", "", "")
    actual_size = file.stat().st_size
    if expected.size and actual_size != expected.size:
        return VerifyResult(
            False,
            f"size mismatch: expected {expected.size}, got {actual_size}",
            "",
            "",
            "",
        )
    sha1_hex, md5_hex, crc_hex = _compute_hashes(file)
    if expected.sha1 and sha1_hex.lower() != expected.sha1.lower():
        return VerifyResult(
            False,
            f"sha1 mismatch: expected {expected.sha1}, got {sha1_hex}",
            sha1_hex,
            crc_hex,
            md5_hex,
        )
    if expected.crc32 and crc_hex.lower() != expected.crc32.lower():
        return VerifyResult(
            False,
            f"crc32 mismatch: expected {expected.crc32}, got {crc_hex}",
            sha1_hex,
            crc_hex,
            md5_hex,
        )
    if expected.md5 and md5_hex.lower() != expected.md5.lower():
        return VerifyResult(
            False,
            f"md5 mismatch: expected {expected.md5}, got {md5_hex}",
            sha1_hex,
            crc_hex,
            md5_hex,
        )
    return VerifyResult(True, None, sha1_hex, crc_hex, md5_hex)


_REGION_PATTERN = re.compile(r"\(([^)]+)\)")


def _extract_regions(name: str) -> list[str]:
    regions: list[str] = []
    for match in _REGION_PATTERN.findall(name):
        for part in match.split(","):
            regions.append(part.strip())
    return regions


def _strip_brackets(name: str) -> str:
    return re.sub(r"\s*[\(\[][^)\]]*[\)\]]", "", name).strip().lower()


def find_game_by_title(
    dat: DatEntry,
    title: str,
    region_priority: list[str],
    exclude_keywords: list[str] | None = None,
) -> GameEntry | None:
    exclude_keywords = exclude_keywords or []
    target = title.strip().lower()
    candidates: list[GameEntry] = []
    for g in dat.games:
        stripped = _strip_brackets(g.name)
        if stripped == target or target in stripped:
            if any(kw.lower() in g.name.lower() for kw in exclude_keywords):
                continue
            candidates.append(g)
    if not candidates:
        return None

    def score(g: GameEntry) -> tuple[int, int]:
        regions = _extract_regions(g.name)
        best_rank = len(region_priority) + 1
        for r in regions:
            for i, pref in enumerate(region_priority):
                if pref.lower() in r.lower() or r.lower() in pref.lower():
                    best_rank = min(best_rank, i)
                    break
        exact_match = 0 if _strip_brackets(g.name) == target else 1
        return (best_rank, exact_match)

    candidates.sort(key=score)
    return candidates[0]
