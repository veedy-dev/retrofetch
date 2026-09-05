from __future__ import annotations

import logging
from collections.abc import Callable

from retrofetch.config import Config, ConsoleOverride
from retrofetch.sources import SourceAdapter

logger = logging.getLogger(__name__)

_SOURCE_FACTORIES: dict[str, Callable[[dict[str, object]], SourceAdapter]] = {
    "archive_org": lambda entry: __import__(
        "retrofetch.sources.archive_org", fromlist=["ArchiveOrgSource"]
    ).ArchiveOrgSource(entry),
    "coolrom": lambda entry: __import__(
        "retrofetch.sources.coolrom", fromlist=["CoolROMSource"]
    ).CoolROMSource(entry),
    "romsfun": lambda entry: __import__(
        "retrofetch.sources.romsfun", fromlist=["RomsfunSource"]
    ).RomsfunSource(entry),
    "romsim": lambda entry: __import__(
        "retrofetch.sources.romsim", fromlist=["RomsimSource"]
    ).RomsimSource(entry),
    "romslab": lambda entry: __import__(
        "retrofetch.sources.romslab", fromlist=["RomsLabSource"]
    ).RomsLabSource(entry),
    "romsretro": lambda entry: __import__(
        "retrofetch.sources.romsretro", fromlist=["RomsretroSource"]
    ).RomsretroSource(entry),
    "vimm": lambda entry: __import__(
        "retrofetch.sources.vimm", fromlist=["VimmSource"]
    ).VimmSource(entry),
    "minerva_http": lambda entry: __import__(
        "retrofetch.sources.minerva_http", fromlist=["MinervaHttpSource"]
    ).MinervaHttpSource(entry),
    "minerva_torrent": lambda entry: __import__(
        "retrofetch.sources.minerva_torrent", fromlist=["MinervaTorrentSource"]
    ).MinervaTorrentSource(entry),
}


def get_wantlist(
    console_entry: dict[str, object],
    overrides: ConsoleOverride | None,
    config: Config,
    limit: int,
) -> list[str]:
    """Return the raw ranked browse catalog for a console.

    Include/exclude overrides are intentionally not applied here. Use
    resolve_download_set() for the final download queue.
    """

    class_key = str(console_entry.get("class", ""))
    source_order = (config.ranking_sources_by_class or {}).get(class_key, [])
    region_priority = (
        overrides.region_priority if overrides and overrides.region_priority else None
    ) or config.region_priority
    source_entry = dict(console_entry)
    source_entry["exclude_keywords"] = list(config.exclude_keywords)
    minerva_path = source_entry.get("minerva_path")
    has_minerva_path = isinstance(minerva_path, str) and bool(
        minerva_path.strip().strip("/")
    )

    titles: list[str] = []
    for source_name in source_order:
        factory = _SOURCE_FACTORIES.get(source_name)
        if factory is None:
            logger.warning("ranker: unknown source %s for class %s", source_name, class_key)
            continue
        try:
            source = factory(source_entry)
            fetched = source.list_popular(limit=limit, region_priority=region_priority)
        except Exception as exc:
            # Provider errors may contain credentials; omit raw text and tracebacks.
            logger.exception(
                "ranker: %s list_popular failed for %s: %s",
                source_name,
                console_entry.get("shortname"),
                type(exc).__name__,
                exc_info=False,
            )
            continue
        if fetched or (
            source_name in {"minerva_http", "minerva_torrent"} and has_minerva_path
        ):
            titles = list(fetched)
            logger.info(
                "ranker: %s supplied %d titles for %s",
                source_name,
                len(titles),
                console_entry.get("shortname"),
            )
            break

    seen: set[str] = set()
    result: list[str] = []
    for title in titles:
        key = title.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(title)
        if limit > 0 and len(result) >= limit:
            break
    return result


def resolve_download_set(
    titles: list[str],
    override: ConsoleOverride | None,
    limit: int,
) -> list[str]:
    """Resolve the actual download queue from a raw catalog and overrides.

    If include is non-empty, the queue is exactly include minus exclude with
    include order preserved. Missing include titles are kept so user-authored
    overrides can still be attempted by exact source lookup.
    """

    include = list(override.include if override else [])
    exclude = {title.casefold() for title in (override.exclude if override else [])}
    catalog_keys = {title.casefold() for title in titles}

    if include:
        result: list[str] = []
        seen: set[str] = set()
        for title in include:
            key = title.casefold()
            if key in seen or key in exclude:
                continue
            seen.add(key)
            if key not in catalog_keys:
                logger.warning("ranker: included title not found in catalog: %s", title)
            result.append(title)
        return result

    result = []
    seen = set()
    for title in titles:
        key = title.casefold()
        if key in seen or key in exclude:
            continue
        seen.add(key)
        result.append(title)
        if limit > 0 and len(result) >= limit:
            break
    return result
