from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from retrofetch.config import Config, ConsoleOverride
# NOTE: ``get_wantlist`` is looked up indirectly via the ranker module each call
# (see ``get_or_fetch_wantlist``) so monkey-patches at ``retrofetch.ranker.get_wantlist``
# keep flowing through, which matters for the existing wave1-4 pilot harness.
from retrofetch import ranker as _ranker

log = logging.getLogger(__name__)

DEFAULT_TTL_HOURS: int = 24


@dataclass(frozen=True)
class CachedWantlist:
    console: str
    titles: list[str]
    cached_at: datetime
    ttl_hours: int


def cache_path(cache_dir: Path, console_shortname: str) -> Path:
    return cache_dir / "wantlists" / f"{console_shortname}.json"


def _parse_cached(raw: Any) -> CachedWantlist | None:
    if not isinstance(raw, dict):
        return None

    console = raw.get("console")
    titles = raw.get("titles")
    cached_at_raw = raw.get("cached_at")
    ttl_hours = raw.get("ttl_hours")

    if not isinstance(console, str):
        return None
    if not isinstance(titles, list) or not all(isinstance(title, str) for title in titles):
        return None
    if not isinstance(cached_at_raw, str):
        return None
    if not isinstance(ttl_hours, int):
        return None

    try:
        cached_at = datetime.fromisoformat(cached_at_raw)
    except ValueError:
        return None
    if cached_at.tzinfo is None:
        return None

    return CachedWantlist(
        console=console,
        titles=list(titles),
        cached_at=cached_at.astimezone(timezone.utc),
        ttl_hours=ttl_hours,
    )


def load_cached(cache_dir: Path, shortname: str) -> CachedWantlist | None:
    path = cache_path(cache_dir, shortname)
    if not path.exists():
        return None

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        log.debug("wantlist_cache: load failed for %s: %s", shortname, exc)
        return None

    entry = _parse_cached(raw)
    if entry is None:
        return None

    now = datetime.now(timezone.utc)
    if now > entry.cached_at + timedelta(hours=entry.ttl_hours):
        return None

    return entry


def save_cached(cache_dir: Path, entry: CachedWantlist) -> None:
    path = cache_path(cache_dir, entry.console)
    payload = {
        "cached_at": entry.cached_at.astimezone(timezone.utc).isoformat(),
        "ttl_hours": entry.ttl_hours,
        "console": entry.console,
        "titles": list(entry.titles),
    }

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(payload, indent=2, ensure_ascii=False))
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def invalidate(cache_dir: Path, shortname: str) -> None:
    path = cache_path(cache_dir, shortname)
    try:
        path.unlink()
    except FileNotFoundError:
        return


def get_or_fetch_wantlist(
    console_entry: dict[str, object],
    overrides: ConsoleOverride | None,
    config: Config,
    limit: int,
) -> tuple[list[str], bool]:
    shortname = str(console_entry.get("shortname", ""))
    cache_dir = Path(config.cache_dir)
    hit = load_cached(cache_dir, shortname)
    if hit is not None:
        return (list(hit.titles), True)

    # Re-resolve through the module to honor monkey-patches at call time.
    titles = _ranker.get_wantlist(
        console_entry=console_entry,
        overrides=overrides,
        config=config,
        limit=limit,
    )
    entry = CachedWantlist(
        console=shortname,
        titles=list(titles),
        cached_at=datetime.now(timezone.utc),
        ttl_hours=DEFAULT_TTL_HOURS,
    )
    try:
        save_cached(cache_dir, entry)
    except OSError as exc:
        log.warning("wantlist_cache: save failed for %s: %s", shortname, exc)
    return (titles, False)
