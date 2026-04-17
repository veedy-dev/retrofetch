"""IGDB OAuth and wantlist generator."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed

from retrofetch.config import ConfigError, IgdbCreds

_log = logging.getLogger(__name__)

_TWITCH_TOKEN_URL = "https://id.twitch.tv/oauth2/token"
_IGDB_GAMES_URL = "https://api.igdb.com/v4/games"
_CATEGORY_WHITELIST = (0, 2, 4)


@dataclass
class OAuthToken:
    access_token: str
    expires_at: float


@dataclass
class IgdbGame:
    id: int
    name: str
    total_rating: float | None
    total_rating_count: int | None
    first_release_date: int | None
    category: int | None


def _token_cache_path(cache_dir: Path) -> Path:
    return cache_dir / "igdb" / "token.json"


def _games_cache_path(cache_dir: Path, platform_id: int) -> Path:
    return cache_dir / "igdb" / f"{platform_id}.json"


def _load_cached_token(cache_dir: Path) -> OAuthToken | None:
    path = _token_cache_path(cache_dir)
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    expires_at = float(raw.get("expires_at", 0))
    if expires_at - time.time() < 60:
        return None
    access_token = raw.get("access_token")
    if not access_token:
        return None
    return OAuthToken(access_token=access_token, expires_at=expires_at)


def _save_cached_token(cache_dir: Path, token: OAuthToken) -> None:
    path = _token_cache_path(cache_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(
            {"access_token": token.access_token, "expires_at": token.expires_at}
        ),
        encoding="utf-8",
    )
    tmp.replace(path)


def get_twitch_token(creds: IgdbCreds, cache_dir: Path = Path(".cache")) -> OAuthToken:
    cached = _load_cached_token(cache_dir)
    if cached is not None:
        return cached
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(
            _TWITCH_TOKEN_URL,
            data={
                "client_id": creds.client_id,
                "client_secret": creds.client_secret,
                "grant_type": "client_credentials",
            },
        )
    if resp.status_code == 400 or resp.status_code == 401:
        raise ConfigError(
            f"IGDB/Twitch OAuth rejected credentials (status {resp.status_code}). "
            "Verify IGDB_CLIENT_ID and IGDB_CLIENT_SECRET at https://dev.twitch.tv/console/apps"
        )
    resp.raise_for_status()
    payload = resp.json()
    expires_at = time.time() + float(payload["expires_in"])
    token = OAuthToken(access_token=payload["access_token"], expires_at=expires_at)
    _save_cached_token(cache_dir, token)
    return token


@retry(
    stop=stop_after_attempt(3),
    wait=wait_fixed(0.26),
    retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
    reraise=True,
)
def _post_apicalypse(url: str, headers: dict[str, str], body: str) -> Any:
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(url, headers=headers, content=body)
    resp.raise_for_status()
    return resp.json()


def fetch_platform_games(
    platform_id: int,
    creds: IgdbCreds,
    cache_dir: Path = Path(".cache"),
    limit: int = 500,
) -> list[IgdbGame]:
    cache_path = _games_cache_path(cache_dir, platform_id)
    if cache_path.exists():
        try:
            raw = json.loads(cache_path.read_text(encoding="utf-8"))
            return [IgdbGame(**g) for g in raw]
        except (json.JSONDecodeError, TypeError, KeyError) as exc:
            _log.warning("Corrupt IGDB cache for platform %s: %s", platform_id, exc)
    token = get_twitch_token(creds, cache_dir)
    headers = {
        "Client-ID": creds.client_id,
        "Authorization": f"Bearer {token.access_token}",
        "Accept": "application/json",
    }
    categories = ",".join(str(c) for c in _CATEGORY_WHITELIST)
    body = (
        f"fields name,total_rating,total_rating_count,first_release_date,category;"
        f"where platforms = [{platform_id}] & category = ({categories}) & total_rating != null;"
        f"sort total_rating desc;"
        f"limit {max(1, min(limit, 500))};"
    )
    data = _post_apicalypse(_IGDB_GAMES_URL, headers, body)
    games: list[IgdbGame] = []
    for entry in data:
        games.append(
            IgdbGame(
                id=int(entry.get("id", 0)),
                name=str(entry.get("name", "")),
                total_rating=entry.get("total_rating"),
                total_rating_count=entry.get("total_rating_count"),
                first_release_date=entry.get("first_release_date"),
                category=entry.get("category"),
            )
        )
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps([g.__dict__ for g in games], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return games


def build_wantlist(
    platform_id: int | None,
    creds: IgdbCreds | None,
    include: list[str],
    exclude: list[str],
    limit: int,
    cache_dir: Path = Path(".cache"),
) -> list[str]:
    raw_titles: list[str] = []
    if platform_id and creds:
        try:
            games = fetch_platform_games(
                platform_id, creds, cache_dir, limit=max(limit * 2, 100)
            )
        except ConfigError:
            raise
        except Exception as exc:
            _log.warning("IGDB fetch failed for platform %s: %s", platform_id, exc)
            games = []

        def sort_key(g: IgdbGame) -> tuple[float, int, int]:
            rating = g.total_rating if g.total_rating is not None else -1.0
            count = g.total_rating_count if g.total_rating_count is not None else 0
            release = g.first_release_date if g.first_release_date is not None else 0
            return (-rating, -count, -release)

        games.sort(key=sort_key)
        raw_titles = [g.name for g in games]

    exclude_set = {e.lower() for e in exclude}
    result: list[str] = []
    seen: set[str] = set()
    for title in include:
        key = title.lower()
        if key in exclude_set or key in seen:
            continue
        result.append(title)
        seen.add(key)
    for title in raw_titles:
        if len(result) >= limit:
            break
        key = title.lower()
        if key in exclude_set or key in seen:
            continue
        result.append(title)
        seen.add(key)
    return result
