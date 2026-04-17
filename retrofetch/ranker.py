from __future__ import annotations

import logging
from typing import Callable

from retrofetch.config import Config, ConsoleOverride
from retrofetch.sources import SourceAdapter

log = logging.getLogger(__name__)

_SOURCE_FACTORIES: dict[str, Callable[[dict[str, object]], SourceAdapter]] = {
    "archive_org": lambda entry: __import__(
        "retrofetch.sources.archive_org", fromlist=["ArchiveOrgSource"]
    ).ArchiveOrgSource(entry),
    "romsfun": lambda entry: __import__(
        "retrofetch.sources.romsfun", fromlist=["RomsfunSource"]
    ).RomsfunSource(entry),
    "romsretro": lambda entry: __import__(
        "retrofetch.sources.romsretro", fromlist=["RomsretroSource"]
    ).RomsretroSource(entry),
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
    class_key = str(console_entry.get("class", ""))
    source_order = (config.ranking_sources_by_class or {}).get(class_key, [])
    region_priority = (
        overrides.region_priority if overrides and overrides.region_priority else None
    ) or config.region_priority
    include = list(overrides.include if overrides else [])
    exclude = [title.lower() for title in (overrides.exclude if overrides else [])]

    titles: list[str] = []
    for source_name in source_order:
        factory = _SOURCE_FACTORIES.get(source_name)
        if factory is None:
            log.warning("ranker: unknown source %s for class %s", source_name, class_key)
            continue
        try:
            source = factory(console_entry)
            fetched = source.list_popular(limit=limit, region_priority=region_priority)
        except Exception as exc:
            log.warning(
                "ranker: %s list_popular failed for %s: %s",
                source_name,
                console_entry.get("shortname"),
                exc,
            )
            continue
        if fetched:
            titles = list(fetched)
            log.info(
                "ranker: %s supplied %d titles for %s",
                source_name,
                len(titles),
                console_entry.get("shortname"),
            )
            break

    seen: set[str] = set()
    result: list[str] = []
    for title in include + titles:
        key = title.lower()
        if key in seen or key in exclude:
            continue
        seen.add(key)
        result.append(title)
        if len(result) >= limit:
            break
    return result
