from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

CATALOG_SCHEMA_VERSION = 4


@dataclass(frozen=True)
class CatalogFile:
    filename: str
    url: str
    size: int | None


@dataclass
class ParsedName:
    title: str
    regions: list[str]
    revision: str | None
    disc: int | None
    tags: list[str]
    is_unlicensed_variant: bool


@dataclass
class CatalogEntry:
    title: str
    region: str
    files: list[CatalogFile]
    source: str
    tags: list[str]


_TOKEN_RE = re.compile(r"\s*(\(([^()]*)\)|\[([^\[\]]*)\])")
_REV_RE = re.compile(r"^(?:rev(?:ision)?\s*)?([0-9]+[A-Za-z]?)$", re.IGNORECASE)
_REV_PREFIX_RE = re.compile(r"^rev(?:ision)?\s+(.+)$", re.IGNORECASE)
_VERSION_RE = re.compile(r"^v(?:er(?:sion)?\.?\s*)?([0-9]+(?:\.[0-9]+)*)$", re.IGNORECASE)
_DISC_RE = re.compile(r"^(?:disc|disk)\s*([0-9]+)", re.IGNORECASE)
_ARTICLES = ("the", "a", "an")
_UNLICENSED_MARKERS = (
    "aftermarket",
    "beta",
    "demo",
    "kiosk",
    "pirate",
    "proto",
    "prototype",
    "sample",
    "trade demo",
    "unl",
    "unlicensed",
)
_BIOS_MARKERS = ("[bios]", "(bios)", " bios ")

_REGION_ALIASES = {
    "Argentina",
    "Asia",
    "Australia",
    "Brazil",
    "Canada",
    "China",
    "Denmark",
    "Europe",
    "Finland",
    "France",
    "Germany",
    "Greece",
    "Hong Kong",
    "Italy",
    "Japan",
    "Korea",
    "Netherlands",
    "Norway",
    "Poland",
    "Portugal",
    "Russia",
    "Spain",
    "Sweden",
    "Taiwan",
    "UK",
    "USA",
    "United Kingdom",
    "Unknown",
    "World",
}


def _stem(filename: str) -> str:
    name = Path(filename).name
    suffix = Path(name).suffix
    if suffix:
        return name[: -len(suffix)]
    return name


def _is_region_token(token: str) -> bool:
    parts = [part.strip() for part in token.split(",")]
    if not parts:
        return False
    return all(part in _REGION_ALIASES for part in parts)


def _split_regions(token: str) -> list[str]:
    return [part.strip() for part in token.split(",") if part.strip()]


def _revision_from_token(token: str) -> str | None:
    prefixed = _REV_PREFIX_RE.match(token)
    if prefixed:
        return prefixed.group(1).strip()
    versioned = _VERSION_RE.match(token)
    if versioned:
        return "v" + versioned.group(1)
    rev = _REV_RE.match(token)
    if rev and token.lower().startswith("rev"):
        return rev.group(1).strip()
    return None


def _is_unlicensed(tags: list[str]) -> bool:
    tag_blob = " ".join(tags).lower()
    return any(marker in tag_blob for marker in _UNLICENSED_MARKERS)


def parse_nointro_name(filename: str) -> ParsedName:
    """Parse the common No-Intro/Redump filename token convention."""

    name = _stem(filename).strip()
    first_token = _TOKEN_RE.search(name)
    title = name[: first_token.start()].strip() if first_token else name
    regions: list[str] = []
    revision: str | None = None
    disc: int | None = None
    tags: list[str] = []

    for match in _TOKEN_RE.finditer(name):
        token = (match.group(2) if match.group(2) is not None else match.group(3) or "").strip()
        if not token:
            continue
        if _is_region_token(token):
            regions.extend(_split_regions(token))
            continue
        rev = _revision_from_token(token)
        if rev is not None:
            revision = rev
            continue
        disc_match = _DISC_RE.match(token)
        if disc_match:
            disc = int(disc_match.group(1))
            continue
        tags.append(token)

    return ParsedName(
        title=title,
        regions=regions,
        revision=revision,
        disc=disc,
        tags=tags,
        is_unlicensed_variant=_is_unlicensed(tags),
    )


def _normalize_title(title: str) -> str:
    value = title.casefold().strip()
    for article in _ARTICLES:
        suffix = f", {article}"
        if value.endswith(suffix):
            value = value[: -len(suffix)]
            break
    for article in _ARTICLES:
        prefix = f"{article} "
        if value.startswith(prefix):
            value = value[len(prefix) :]
            break
    value = re.sub(r"[^0-9a-z]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _region_rank(regions: list[str], priority: list[str]) -> tuple[int, str]:
    if not regions:
        return (len(priority), "Unknown")
    priority_lc = [region.casefold() for region in priority]
    for index, wanted in enumerate(priority_lc):
        for region in regions:
            if region.casefold() == wanted:
                return (index, region)
    return (len(priority), regions[0])


def _revision_score(revision: str | None) -> tuple[int, ...]:
    if not revision:
        return (0,)
    numbers = [int(part) for part in re.findall(r"\d+", revision)]
    if numbers:
        return tuple(numbers)
    return (0,)


def _release_key(parsed: ParsedName, priority: list[str]) -> tuple[int, str, tuple[int, ...]]:
    region_rank, region = _region_rank(parsed.regions, priority)
    return (region_rank, region.casefold(), _revision_score(parsed.revision))


def _should_exclude(filename: str, parsed: ParsedName, exclude_keywords: list[str]) -> bool:
    lowered = f" {filename.casefold()} "
    for marker in _BIOS_MARKERS:
        if marker in lowered:
            return True
    if parsed.is_unlicensed_variant:
        return True
    for keyword in exclude_keywords:
        if keyword and keyword.casefold() in filename.casefold():
            return True
    return False


def _entry_for_file(
    catalog_file: CatalogFile, parsed: ParsedName, region_priority: list[str]
) -> CatalogEntry:
    _rank, region = _region_rank(parsed.regions, region_priority)
    return CatalogEntry(
        title=parsed.title,
        region=region,
        files=[catalog_file],
        source="catalog",
        tags=list(parsed.tags),
    )


def build_catalog(
    files: list[CatalogFile],
    *,
    region_priority: list[str],
    exclude_keywords: list[str],
    one_g_one_r: bool = True,
) -> list[CatalogEntry]:
    parsed_files: list[tuple[CatalogFile, ParsedName]] = []
    for catalog_file in files:
        parsed = parse_nointro_name(catalog_file.filename)
        if not parsed.title:
            continue
        if _should_exclude(catalog_file.filename, parsed, exclude_keywords):
            continue
        parsed_files.append((catalog_file, parsed))

    if not one_g_one_r:
        return [
            _entry_for_file(catalog_file, parsed, region_priority)
            for catalog_file, parsed in parsed_files
        ]

    grouped: dict[str, list[tuple[CatalogFile, ParsedName]]] = {}
    for catalog_file, parsed in parsed_files:
        grouped.setdefault(_normalize_title(parsed.title), []).append((catalog_file, parsed))

    entries: list[CatalogEntry] = []
    for group in grouped.values():
        best_region_rank = min(_release_key(parsed, region_priority)[0] for _file, parsed in group)
        region_candidates = [
            item for item in group if _release_key(item[1], region_priority)[0] == best_region_rank
        ]
        best_revision = max(_revision_score(parsed.revision) for _file, parsed in region_candidates)
        release = [
            item
            for item in region_candidates
            if _revision_score(item[1].revision) == best_revision
        ]
        release.sort(key=lambda item: (item[1].disc is None, item[1].disc or 0, item[0].filename))
        _display_file, display_parsed = release[0]
        _rank, region = _region_rank(display_parsed.regions, region_priority)
        tags: list[str] = []
        for _file, parsed in release:
            for tag in parsed.tags:
                if tag not in tags:
                    tags.append(tag)
        entries.append(
            CatalogEntry(
                title=display_parsed.title,
                region=region,
                files=[catalog_file for catalog_file, _parsed in release],
                source="catalog",
                tags=tags,
            )
        )

    entries.sort(key=lambda entry: entry.title.casefold())
    return entries
