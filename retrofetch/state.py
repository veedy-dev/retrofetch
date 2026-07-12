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

STATE_VERSION = 2

GameStatus = Literal[
    "pending", "acquired", "unverified", "failed", "skipped", "cancelled"
]
TerminalOutcome = Literal["acquired", "failed", "skipped", "cancelled"]
TransferPhase = Literal["planned", "attached", "downloading", "finalizing", "terminal"]
VerificationStatus = Literal["verified", "unverified", "not_applicable"]

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
    item_id: str | None = None
    provider: str | None = None
    infohash: str | None = None
    tag: str | None = None
    selected_file_ids: list[int] = field(default_factory=list)
    selected_paths: list[str] = field(default_factory=list)
    staging_path: str | None = None
    final_path: str | None = None
    selected_bytes: int | None = None
    completed_bytes: int = 0
    phase: TransferPhase | None = None
    outcome: TerminalOutcome | None = None
    verification: VerificationStatus | None = None


@dataclass
class State:
    version: int = STATE_VERSION
    console: str = ""
    last_run: str | None = None
    games: list[GameEntry] = field(default_factory=list)


def state_path(console: str, roms_root: Path) -> Path:
    return Path(roms_root) / console / ".retrofetch-state.json"


def _coerce_game(g: dict[str, Any]) -> GameEntry:
    attempts_raw = g.get("attempts", []) or []
    attempts = [GameAttempt(**a) for a in attempts_raw]
    status = g.get("status", "pending")
    outcome = g.get("outcome")
    verification = g.get("verification")
    if outcome is None:
        if status in ("acquired", "unverified"):
            outcome = "acquired"
        elif status in ("failed", "skipped", "cancelled"):
            outcome = status
    if verification is None:
        if status == "acquired":
            verification = "verified"
        elif status == "unverified":
            verification = "unverified"
        elif outcome is not None:
            verification = "not_applicable"
    size_bytes = g.get("size_bytes")
    return GameEntry(
        title=g["title"],
        status=status,
        source=g.get("source"),
        filename=g.get("filename"),
        sha1=g.get("sha1"),
        crc32=g.get("crc32"),
        size_bytes=size_bytes,
        attempts=attempts,
        item_id=g.get("item_id"),
        provider=g.get("provider", g.get("source")),
        infohash=g.get("infohash"),
        tag=g.get("tag"),
        selected_file_ids=list(g.get("selected_file_ids", []) or []),
        selected_paths=list(g.get("selected_paths", []) or []),
        staging_path=g.get("staging_path"),
        final_path=g.get("final_path"),
        selected_bytes=g.get("selected_bytes", size_bytes),
        completed_bytes=g.get(
            "completed_bytes", size_bytes if outcome == "acquired" and size_bytes else 0
        ),
        phase=g.get("phase", "terminal" if outcome is not None else None),
        outcome=outcome,
        verification=verification,
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
    state.version = STATE_VERSION
    state.last_run = datetime.now(timezone.utc).isoformat()
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(asdict(state), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    os.replace(tmp, path)


def update_game(state: State, title: str, **fields: Any) -> State:
    item_id = fields.get("item_id")
    game = None
    if item_id is not None:
        game = next((entry for entry in state.games if entry.item_id == item_id), None)
        if game is None:
            game = next(
                (
                    entry
                    for entry in state.games
                    if entry.item_id is None and entry.title == title
                ),
                None,
            )
    else:
        game = next((entry for entry in state.games if entry.title == title), None)
    if game is not None:
        for key, value in fields.items():
            setattr(game, key, value)
        return state
    state.games.append(GameEntry(title=title, **fields))
    return state
