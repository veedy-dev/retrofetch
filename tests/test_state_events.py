from __future__ import annotations

import json

from retrofetch.events import (
    EventBus,
    GameCancelledEvent,
    GameStageEvent,
    GameStartEvent,
)
from retrofetch.state import (
    STATE_VERSION,
    GameEntry,
    State,
    load_state,
    save_state,
    update_game,
)
from retrofetch.tui.downloads import DownloadSession
from retrofetch.tui.messages import EventBusBridge


def test_v1_state_loads_and_saves_as_v2(scratch_path) -> None:
    state_file = scratch_path / "psp" / ".retrofetch-state.json"
    state_file.parent.mkdir(parents=True)
    state_file.write_text(
        json.dumps(
            {
                "version": 1,
                "console": "psp",
                "games": [
                    {
                        "title": "Game",
                        "status": "acquired",
                        "source": "archive_org",
                        "filename": "Game.zip",
                        "size_bytes": 123,
                        "attempts": [
                            {"source": "archive_org", "result": "ok", "ts": "now"}
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    state = load_state("psp", scratch_path)

    assert state.version == 1
    assert state.games[0].filename == "Game.zip"
    assert state.games[0].outcome == "acquired"
    assert state.games[0].verification == "verified"
    assert state.games[0].completed_bytes == 123

    save_state(state, scratch_path)
    saved = json.loads(state_file.read_text(encoding="utf-8"))
    assert saved["version"] == STATE_VERSION


def test_torrent_lifecycle_round_trips_and_updates_by_item_id(scratch_path) -> None:
    entry = GameEntry(
        title="Game",
        item_id="psp:game",
        provider="minerva_torrent",
        infohash="abc123",
        tag="retrofetch-run",
        selected_file_ids=[7],
        selected_paths=["collection/Game.zip"],
        staging_path=".retrofetch-torrents/abc123",
        final_path="Game.zip",
        selected_bytes=100,
        completed_bytes=40,
        phase="downloading",
        verification="not_applicable",
    )
    state = State(console="psp", games=[entry])
    save_state(state, scratch_path)

    loaded = load_state("psp", scratch_path)
    assert loaded.games == [entry]

    update_game(
        loaded,
        "Game",
        item_id="psp:game",
        completed_bytes=100,
        phase="terminal",
        status="cancelled",
        outcome="cancelled",
    )
    assert len(loaded.games) == 1
    assert loaded.games[0].completed_bytes == 100
    assert loaded.games[0].outcome == "cancelled"

    loaded.games.insert(0, GameEntry(title="Game"))
    update_game(loaded, "Game", item_id="psp:game", completed_bytes=90)
    assert loaded.games[0].completed_bytes == 0
    assert loaded.games[1].completed_bytes == 90


def test_bridge_cancellation_leaves_same_title_sibling_running() -> None:
    session = DownloadSession({"shortname": "psp"}, ["Shared title", "Shared title"])
    bus = EventBus()
    bridge = EventBusBridge(session.apply, bus)
    bridge.start()
    try:
        for item_id, stage in (("first", "Connecting"), ("second", "Downloading")):
            bus.publish(
                GameStartEvent("Shared title", "archive_org", "psp", item_id=item_id)
            )
            bus.publish(GameStageEvent("Shared title", stage, item_id=item_id))
        bus.publish(
            GameCancelledEvent("Shared title", "Cancelled by user", item_id="second")
        )
        assert set(session.active) == {"first"}
        assert session.active["first"].stage == "Connecting"
        assert session.cancelled == 1
    finally:
        bridge.stop()
