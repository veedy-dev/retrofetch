from __future__ import annotations

import argparse
import html
import io
import os
import random
import re
import sys
import time
import unicodedata
from html.parser import HTMLParser
from pathlib import Path

import cloudscraper

from retrofetch.config import _yaml_rt

ROOT = Path(__file__).resolve().parents[2]
CONSOLES_YML = ROOT / "consoles.yml"
SITE_URLS = {
    "romsfun": "https://romsfun.com/roms/",
    "romsretro": "https://romsretro.com/roms/",
}
TARGET_CLASSES = {"A", "B", "C"}
VENDORS = (
    "nintendo ",
    "sega ",
    "sony ",
    "atari ",
    "nec ",
    "snk ",
    "commodore ",
    "panasonic ",
    "emerson ",
    "bandai ",
    "amstrad ",
    "mattel ",
    "magnavox ",
    "gce ",
    "vectrex ",
    "coleco ",
    "casio ",
    "microsoft ",
    "nokia ",
    "philips ",
    "hartung ",
)
ALIASES = {
    "3do": ["3do", "panasonic 3do interactive multiplayer"],
    "amigacd32": ["commodore amiga cd32", "amiga cd32"],
    "arcadia": ["emerson arcadia 2001", "arcadia 2001"],
    "astrocde": ["bally astrocade", "astrocade"],
    "atarijaguar": ["atari jaguar", "jaguar"],
    "atarilynx": ["atari lynx", "lynx"],
    "c64": ["commodore 64", "c64"],
    "cdimono1": ["philips cd-i", "cdi", "cd i"],
    "cdtv": ["commodore cdtv", "cdtv"],
    "fds": ["nintendo family computer disk system", "family computer disk system", "famicom disk system", "fds"],
    "gamegear": ["sega game gear", "game gear", "gg"],
    "gb": ["nintendo game boy", "game boy", "gb"],
    "gba": ["nintendo game boy advance", "game boy advance", "gba"],
    "gbc": ["nintendo game boy color", "game boy color", "gbc"],
    "gc": ["nintendo gamecube", "gamecube", "game cube", "gc"],
    "genesis": ["sega genesis", "genesis", "mega drive", "sega mega drive", "md"],
    "gmaster": ["hartung game master", "game master"],
    "mark3": ["sega mark iii", "mark iii", "mark 3"],
    "mastersystem": ["sega master system", "master system", "sms"],
    "megacd": ["sega cd", "mega cd", "sega mega cd"],
    "megacdjp": ["sega cd", "mega cd", "sega mega cd"],
    "megadrive": ["sega mega drive", "mega drive", "sega genesis", "genesis", "md"],
    "megadrivejp": ["sega mega drive", "mega drive", "sega genesis", "genesis", "md"],
    "multivision": ["othello multivision", "multivision"],
    "n3ds": ["nintendo 3ds", "3ds"],
    "n64": ["nintendo 64", "n64"],
    "n64dd": ["nintendo 64dd", "64dd", "64 dd"],
    "nds": ["nintendo ds", "nds", "ds"],
    "neogeo": ["snk neo geo", "neo geo"],
    "neogeocd": ["snk neo geo cd", "neo geo cd"],
    "neogeocdjp": ["snk neo geo cd", "neo geo cd"],
    "ngp": ["snk neo geo pocket", "neo geo pocket", "ngp"],
    "ngpc": ["snk neo geo pocket color", "neo geo pocket color", "ngpc"],
    "pcengine": ["nec pc engine", "pc engine"],
    "pcenginecd": ["nec pc engine cd", "pc engine cd", "pc engine cd-rom"],
    "pokemini": ["pokemon mini", "poke mini"],
    "ps2": ["sony playstation 2", "playstation 2", "ps2"],
    "ps3": ["sony playstation 3", "playstation 3", "ps3"],
    "psp": ["sony psp", "playstation portable", "psp"],
    "psvita": ["sony ps vita", "playstation vita", "ps vita", "vita", "psvita"],
    "psx": ["sony playstation", "playstation", "ps1", "psx"],
    "satellaview": ["nintendo satellaview", "satellaview"],
    "saturn": ["sega saturn", "saturn"],
    "saturnjp": ["sega saturn", "saturn"],
    "sega32x": ["sega 32x", "32x"],
    "sega32xjp": ["sega 32x", "32x"],
    "sega32xna": ["sega 32x", "32x"],
    "segacd": ["sega cd", "mega cd", "sega mega cd"],
    "sfc": ["super famicom", "sfc"],
    "sg-1000": ["sega sg-1000", "sg 1000", "sg1000"],
    "sgb": ["super game boy", "sgb"],
    "snes": ["super nintendo entertainment system", "super nintendo", "snes"],
    "snesna": ["super nintendo entertainment system", "super nintendo", "snes"],
    "tg-cd": ["turbografx cd", "turbo grafx cd", "pc engine cd", "pc engine cd-rom"],
    "tg16": ["nec turbografx-16", "turbografx-16", "turbografx 16", "turbo grafx 16", "tg16"],
    "virtualboy": ["nintendo virtual boy", "virtual boy", "vb"],
    "wii": ["nintendo wii", "wii"],
    "wiiu": ["nintendo wii u", "wii u", "wiiu"],
    "wonderswan": ["bandai wonderswan", "wonderswan", "ws"],
    "wonderswancolor": ["bandai wonderswan color", "wonderswan color", "wsc"],
}


class RomsParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.pairs: list[tuple[str, str]] = []
        self._href: str | None = None
        self._chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        href = dict(attrs).get("href")
        if href and re.fullmatch(r"(?:https://[^/]+)?/roms/[^/]+/", href):
            self._href = href
            self._chunks = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._chunks.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or self._href is None:
            return
        text = " ".join("".join(self._chunks).split())
        if text:
            slug = self._href.strip("/").split("/")[-1]
            self.pairs.append((text, slug))
        self._href = None
        self._chunks = []


def normalize(value: str) -> str:
    value = html.unescape(value)
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    value = value.lower().strip()
    value = value.replace("&", " and ")
    value = value.replace("+", " plus ")
    value = re.sub(r"\b\d[\d,]*\s+roms?\b.*$", " ", value)
    value = re.sub(r"\broms?\b$", " ", value)
    value = re.sub(r"[()\[\]{}'’:.,/]+", " ", value)
    value = value.replace("-", " ")
    value = re.sub(r"\bvideo game system\b", " ", value)
    value = re.sub(r"\binteractive multiplayer\b", " ", value)
    value = re.sub(r"\bentertainment system\b", " ", value)
    value = re.sub(r"\bcomputer system\b", " ", value)
    value = re.sub(r"\bconsole\b", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def useful_key(value: str) -> bool:
    return bool(value) and re.fullmatch(r"\d+", value) is None


def strip_vendor(text: str) -> str:
    for vendor in VENDORS:
        if text.startswith(vendor):
            return text[len(vendor):].strip()
    return text


def variant_set(value: str) -> set[str]:
    base = normalize(value)
    variants = {base, strip_vendor(base), base.replace(" ", "")}
    return {variant for variant in variants if useful_key(variant)}


def build_site_index(mapping: dict[str, str]) -> dict[str, tuple[str, str]]:
    index: dict[str, tuple[str, str]] = {}
    for display_name, slug in mapping.items():
        for variant in variant_set(display_name):
            if variant not in index:
                index[variant] = (display_name, slug)
    return index


def candidate_keys(entry: dict) -> list[str]:
    keys: list[str] = []
    display_name = entry.get("display_name")
    if isinstance(display_name, str):
        keys.extend(variant_set(display_name))
    shortname = entry.get("shortname")
    if isinstance(shortname, str):
        keys.extend(variant_set(shortname))
        for alias in ALIASES.get(shortname, []):
            keys.extend(variant_set(alias))
    seen: set[str] = set()
    ordered: list[str] = []
    for key in keys:
        if key not in seen:
            seen.add(key)
            ordered.append(key)
    return ordered


def fetch(url: str) -> str:
    last: Exception | None = None
    for attempt in range(3):
        try:
            response = cloudscraper.create_scraper().get(url, timeout=30)
            response.raise_for_status()
            return response.text
        except Exception as exc:
            last = exc
            if attempt < 2:
                time.sleep(5)
    raise RuntimeError(f"failed to fetch {url}: {last}")


def scrape_site(name: str) -> dict[str, str]:
    parser = RomsParser()
    parser.feed(fetch(SITE_URLS[name]))
    mapping: dict[str, str] = {}
    for display_name, slug in parser.pairs:
        mapping[display_name] = slug
    return mapping


def load_yaml():
    return _yaml_rt.load(CONSOLES_YML.read_text(encoding="utf-8"))


def save_yaml(data) -> None:
    buf = io.StringIO()
    _yaml_rt.dump(data, buf)
    tmp = CONSOLES_YML.with_suffix(CONSOLES_YML.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(buf.getvalue())
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, CONSOLES_YML)


def collect_drift(data, site_mappings: dict[str, dict[str, str]]):
    site_indexes = {site: build_site_index(mapping) for site, mapping in site_mappings.items()}
    changes = {"romsfun": [], "romsretro": []}
    no_match: list[str] = []
    for entry in data.get("consoles", []):
        if entry.get("class") not in TARGET_CLASSES:
            continue
        shortname = entry.get("shortname")
        keys = candidate_keys(entry)
        found_any = False
        for site, field in (("romsfun", "romsfun_slug"), ("romsretro", "romsretro_slug")):
            match = None
            for key in keys:
                match = site_indexes[site].get(key)
                if match:
                    break
            if not match:
                continue
            found_any = True
            _, new_slug = match
            old_slug = entry.get(field)
            if field in entry and old_slug != new_slug:
                changes[site].append({
                    "shortname": shortname,
                    "old": old_slug,
                    "new": new_slug,
                })
        if not found_any:
            no_match.append(shortname)
    return changes, no_match


def apply_changes(data, changes) -> None:
    lookup = {
        (item["shortname"], site): item["new"]
        for site, items in changes.items()
        for item in items
    }
    for entry in data.get("consoles", []):
        for site, field in (("romsfun", "romsfun_slug"), ("romsretro", "romsretro_slug")):
            key = (entry.get("shortname"), site)
            if key in lookup and field in entry:
                entry[field] = lookup[key]


def probe(data, changes, seed: int, count: int) -> list[str]:
    changed_shortnames = {
        item["shortname"]
        for site in ("romsfun", "romsretro")
        for item in changes[site]
    }
    candidates = []
    for entry in data.get("consoles", []):
        if entry.get("shortname") not in changed_shortnames:
            continue
        if entry.get("class") not in TARGET_CLASSES:
            continue
        if entry.get("romsfun_slug") and entry.get("romsretro_slug"):
            candidates.append(entry)
    rng = random.Random(seed)
    rng.shuffle(candidates)
    selected = candidates[:count]
    lines: list[str] = []
    for entry in selected:
        shortname = entry["shortname"]
        for site, field in (("romsfun", "romsfun_slug"), ("romsretro", "romsretro_slug")):
            slug = entry[field]
            url = f"{SITE_URLS[site]}{slug}/"
            status = cloudscraper.create_scraper().get(url, timeout=30).status_code
            lines.append(f"PROBE {shortname} {site} {slug} -> {status}")
    return lines


def print_summary(changes, no_match, site_mappings, show_samples: bool) -> None:
    for site, mapping in site_mappings.items():
        print(f"{site}: scraped {len(mapping)} console links")
        if show_samples:
            for display_name, slug in list(mapping.items())[:10]:
                print(f"  SAMPLE {display_name} => {slug}")
    total_fun = len(changes["romsfun"])
    total_retro = len(changes["romsretro"])
    both = len({item["shortname"] for item in changes["romsfun"]} & {item["shortname"] for item in changes["romsretro"]})
    print(f"changes romsfun={total_fun} romsretro={total_retro} both={both}")
    for site in ("romsfun", "romsretro"):
        print(f"[{site}]")
        for item in changes[site]:
            print(f"  {item['shortname']}: {item['old']} -> {item['new']}")
    print("[no-match]")
    for shortname in no_match:
        print(f"  {shortname}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--probe-count", type=int, default=0)
    parser.add_argument("--probe-seed", type=int, default=6)
    parser.add_argument("--show-samples", action="store_true")
    args = parser.parse_args(argv)

    site_mappings = {site: scrape_site(site) for site in ("romsfun", "romsretro")}
    data = load_yaml()
    changes, no_match = collect_drift(data, site_mappings)
    print_summary(changes, no_match, site_mappings, args.show_samples)
    if args.apply:
        apply_changes(data, changes)
        save_yaml(data)
        data = load_yaml()
        print("applied consoles.yml updates")
    if args.probe_count > 0:
        for line in probe(data, changes, seed=args.probe_seed, count=args.probe_count):
            print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
