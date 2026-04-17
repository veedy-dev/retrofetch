"""Per-console JSON state persistence."""

from __future__ import annotations

import json
import logging
import os
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

GameStatus = Literal["pending", "acquired", "unverified", "failed"]

_log = logging.getLogger(__name__)


@dataclass
class GameAttempt:
    source: str
    result: str
    ts: str


@dataclass
class GameEntry:
    title: str
    status: GameStatus = "pending"
    source: str | None = None
    filename: str | None = None
    sha1: str | None = None
    crc32: str | None = None
    size_bytes: int | None = None
    attempts: list[GameAttempt] = field(default_factory=list)


@dataclass
class State:
    version: int = 1
    console: str = ""
    last_run: str | None = None
    games: list[GameEntry] = field(default_factory=list)


def state_path(console: str, roms_root: Path) -> Path:
    return Path(roms_root) / console / ".retrofetch-state.json"


def _coerce_game(g: dict[str, Any]) -> GameEntry:
    attempts_raw = g.get("attempts", []) or []
    attempts = [GameAttempt(**a) for a in attempts_raw]
    return GameEntry(
        title=g["title"],
        status=g.get("status", "pending"),
        source=g.get("source"),
        filename=g.get("filename"),
        sha1=g.get("sha1"),
        crc32=g.get("crc32"),
        size_bytes=g.get("size_bytes"),
        attempts=attempts,
    )


def load_state(console: str, roms_root: Path) -> State:
    path = state_path(console, roms_root)
    if not path.exists():
        return State(console=console)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        ts = int(datetime.now(timezone.utc).timestamp())
        corrupt = path.with_name(path.name + f".corrupt.{ts}")
        shutil.move(str(path), str(corrupt))
        _log.warning("Corrupt state for %s moved to %s: %s", console, corrupt, exc)
        return State(console=console)
    if not isinstance(raw, dict):
        return State(console=console)
    games = [_coerce_game(g) for g in raw.get("games", []) if isinstance(g, dict)]
    return State(
        version=int(raw.get("version", 1)),
        console=str(raw.get("console", console)),
        last_run=raw.get("last_run"),
        games=games,
    )


def save_state(state: State, roms_root: Path) -> None:
    path = state_path(state.console, roms_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    state.last_run = datetime.now(timezone.utc).isoformat()
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(asdict(state), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    os.replace(tmp, path)


def update_game(state: State, title: str, **fields: Any) -> State:
    for g in state.games:
        if g.title == title:
            for k, v in fields.items():
                setattr(g, k, v)
            return state
    state.games.append(GameEntry(title=title, **fields))
    return state
