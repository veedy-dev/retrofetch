from __future__ import annotations

import html
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from retrofetch.config import Config, ConsoleOverride
from retrofetch.catalog import CATALOG_SCHEMA_VERSION
# NOTE: ``get_wantlist`` is looked up indirectly via the ranker module each call
# (see ``get_or_fetch_wantlist``) so monkey-patches at ``retrofetch.ranker.get_wantlist``
# keep flowing through, which matters for the existing wave1-4 pilot harness.
from retrofetch import ranker as _ranker

log = logging.getLogger(__name__)

DEFAULT_TTL_HOURS: int = 24
# How long an "empty result" marker stays active before we retry the fetch.
# Shorter than DEFAULT_TTL_HOURS so users see their consoles recover quickly
# after a transient outage, but long enough that the sidebar stays accurately
# dim across a normal session.
EMPTY_MARKER_TTL_HOURS: int = 2


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
    if raw.get("schema_version") != CATALOG_SCHEMA_VERSION:
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
        _delete_cache_file(path)
        return None

    entry = _parse_cached(raw)
    if entry is None:
        _delete_cache_file(path)
        return None

    now = datetime.now(timezone.utc)
    if now > entry.cached_at + timedelta(hours=entry.ttl_hours):
        _delete_cache_file(path)
        return None

    return entry


def save_cached(cache_dir: Path, entry: CachedWantlist) -> None:
    path = cache_path(cache_dir, entry.console)
    payload = {
        "schema_version": CATALOG_SCHEMA_VERSION,
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
    # Clearing the cache also clears any prior empty-marker so the user's
    # manual retry starts from a clean slate.
    clear_empty_marker(cache_dir, shortname)


def _empty_marker_path(cache_dir: Path, shortname: str) -> Path:
    return cache_dir / "empty_marks" / f"{shortname}.json"


def _delete_cache_file(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except OSError as exc:
        log.debug("wantlist_cache: failed to delete invalid cache %s: %s", path, exc)


def mark_empty(cache_dir: Path, shortname: str) -> None:
    """Record that a recent fetch for ``shortname`` returned zero titles.

    The UI reads this via ``is_recently_empty`` to color the sidebar row grey.
    Silently swallows I/O errors so a failed marker write never blocks the
    fetch path.
    """
    path = _empty_marker_path(cache_dir, shortname)
    payload = {
        "schema_version": CATALOG_SCHEMA_VERSION,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "ttl_hours": EMPTY_MARKER_TTL_HOURS,
        "console": shortname,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(payload, indent=2, ensure_ascii=False))
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except OSError as exc:
        log.debug("wantlist_cache: mark_empty failed for %s: %s", shortname, exc)


def clear_empty_marker(cache_dir: Path, shortname: str) -> None:
    """Idempotent delete of any prior empty-marker for ``shortname``."""
    try:
        _empty_marker_path(cache_dir, shortname).unlink()
    except FileNotFoundError:
        return
    except OSError as exc:
        log.debug(
            "wantlist_cache: clear_empty_marker failed for %s: %s", shortname, exc
        )


def is_recently_empty(cache_dir: Path, shortname: str) -> bool:
    """Return True iff a recent empty-marker exists and is within TTL."""
    path = _empty_marker_path(cache_dir, shortname)
    if not path.exists():
        return False
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        _delete_cache_file(path)
        return False
    if not isinstance(raw, dict):
        _delete_cache_file(path)
        return False
    if raw.get("schema_version") != CATALOG_SCHEMA_VERSION:
        _delete_cache_file(path)
        return False
    recorded_raw = raw.get("recorded_at")
    ttl_hours = raw.get("ttl_hours", EMPTY_MARKER_TTL_HOURS)
    if not isinstance(recorded_raw, str) or not isinstance(ttl_hours, int):
        return False
    try:
        recorded = datetime.fromisoformat(recorded_raw)
    except ValueError:
        _delete_cache_file(path)
        return False
    if recorded.tzinfo is None:
        _delete_cache_file(path)
        return False
    now = datetime.now(timezone.utc)
    is_fresh = now <= recorded + timedelta(hours=ttl_hours)
    if not is_fresh:
        _delete_cache_file(path)
    return is_fresh


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
        return ([html.unescape(t) for t in hit.titles], True)

    # Re-resolve through the module to honor monkey-patches at call time.
    raw_titles = _ranker.get_wantlist(
        console_entry=console_entry,
        overrides=overrides,
        config=config,
        limit=limit,
    )
    # Decode HTML entities from scraped HTML sources.
    titles = [html.unescape(t) for t in raw_titles]
    # Empty list = no provider carries this console (or transient outage).
    # We do NOT persist an empty wantlist as a normal cache file (that would
    # block retries for 24h). Instead we write a short-lived empty-marker so
    # the UI can grey out the sidebar row without permanently pinning it.
    if not titles:
        log.info(
            "wantlist_cache: empty result for %s - recording short-lived marker",
            shortname,
        )
        mark_empty(cache_dir, shortname)
        return (titles, False)
    # Non-empty result: clear any stale empty-marker from a prior run so the
    # UI recovers the green state immediately.
    clear_empty_marker(cache_dir, shortname)
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
