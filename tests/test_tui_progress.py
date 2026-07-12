from __future__ import annotations

import asyncio
import re
import threading
from pathlib import Path
from typing import Any

from textual.app import App
from textual.widgets import Label, ProgressBar

import retrofetch.tui.screens.download_progress as download_progress_module
from retrofetch.orchestrator import RunReport
from retrofetch.tui.messages import (
    DownloadComplete,
    GameBytes,
    GameCancelled,
    GameDone,
    GameFailed,
    GameStage,
    GameStart,
)
from retrofetch.tui.screens.download_progress import DownloadProgressScreen

_SPEED_RE = re.compile(r"\d+(\.\d+)? (KB|MB)/s")


class _TestProgressScreen(DownloadProgressScreen):
    def on_mount(self) -> None:
        return None


class _ProgressApp(App[None]):
    def __init__(self, screen: DownloadProgressScreen) -> None:
        super().__init__()
        self.screen_to_push = screen
        self.config = type("ConfigStub", (), {"roms_root": Path("ROMs")})()
        self.consoles_yml: dict[str, Any] = {"consoles": []}

    async def on_mount(self) -> None:
        await self.push_screen(self.screen_to_push)


def _bar(screen: DownloadProgressScreen) -> ProgressBar:
    return screen.query_one("#progress-overall-bar", ProgressBar)


def _header(screen: DownloadProgressScreen) -> str:
    return str(screen.query_one("#progress-overall-text", Label).content)


def _summary(screen: DownloadProgressScreen) -> str:
    return str(screen.query_one("#summary-line", Label).content)


def _percentage(screen: DownloadProgressScreen) -> float:
    return (_bar(screen).percentage or 0.0) * 100


def _run(screen: DownloadProgressScreen, body) -> None:
    app = _ProgressApp(screen)

    async def run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            body(screen)
            await pilot.pause()

    asyncio.run(run())


def test_all_fail_progress_reaches_full_bar(monkeypatch, scratch_path) -> None:
    monkeypatch.chdir(scratch_path)
    screen = _TestProgressScreen(
        console_entry={"shortname": "gb", "class": "A"},
        wantlist=[f"Game {index}" for index in range(7)],
        dry_run=False,
    )

    def body(current: DownloadProgressScreen) -> None:
        for index in range(7):
            current.on_game_failed(GameFailed(game=f"Game {index}", reason="nope"))
        current.on_download_complete(
            DownloadComplete(
                RunReport(
                    console="gb",
                    attempted=7,
                    acquired=0,
                    failed=7,
                    unverified=0,
                    skipped=0,
                )
            )
        )
        assert round(_percentage(current)) == 100
        assert _header(current) == "Overall: 7 / 7 games (7 failed)"
        assert _summary(current) == (
            "Done. attempted=7 acquired=0 failed=7 unverified=0. Press Esc to return."
        )

    _run(screen, body)


def test_mixed_progress_tracks_all_processed_games(monkeypatch, scratch_path) -> None:
    monkeypatch.chdir(scratch_path)
    screen = _TestProgressScreen(
        console_entry={"shortname": "gb", "class": "A"},
        wantlist=[f"Game {index}" for index in range(7)],
        dry_run=False,
    )

    def body(current: DownloadProgressScreen) -> None:
        for index in range(3):
            current.on_game_done(
                GameDone(
                    game=f"Game {index}", source="archive_org", size=123, sha1=None
                )
            )
        for index in range(3, 7):
            current.on_game_failed(GameFailed(game=f"Game {index}", reason="nope"))
        current.on_download_complete(
            DownloadComplete(
                RunReport(
                    console="gb",
                    attempted=7,
                    acquired=3,
                    failed=4,
                    unverified=0,
                    skipped=0,
                )
            )
        )
        assert round(_percentage(current)) == 100
        assert _header(current) == "Overall: 7 / 7 games (4 failed)"
        assert _summary(current) == (
            "Done. attempted=7 acquired=3 failed=4 unverified=0. Press Esc to return."
        )

    _run(screen, body)


def test_all_success_reaches_full_bar(monkeypatch, scratch_path) -> None:
    monkeypatch.chdir(scratch_path)
    screen = _TestProgressScreen(
        console_entry={"shortname": "gb", "class": "A"},
        wantlist=[f"Game {index}" for index in range(5)],
        dry_run=False,
    )

    def body(current: DownloadProgressScreen) -> None:
        for index in range(5):
            current.on_game_done(
                GameDone(
                    game=f"Game {index}", source="archive_org", size=123, sha1=None
                )
            )
        current.on_download_complete(
            DownloadComplete(
                RunReport(
                    console="gb",
                    attempted=5,
                    acquired=5,
                    failed=0,
                    unverified=0,
                    skipped=0,
                )
            )
        )
        assert round(_percentage(current)) == 100
        assert _header(current) == "Overall: 5 / 5 games (0 failed)"

    _run(screen, body)


def _make_screen(wantlist: list[str]) -> DownloadProgressScreen:
    return _TestProgressScreen(
        console_entry={"shortname": "gb", "class": "A"},
        wantlist=wantlist,
        dry_run=False,
    )


def _active_text(screen: DownloadProgressScreen, game: str) -> str:
    return str(screen._active[game].content)


def _fake_clock(monkeypatch) -> dict[str, float]:
    clock = {"now": 100.0}
    monkeypatch.setattr(download_progress_module, "monotonic", lambda: clock["now"])
    return clock


def test_active_row_shows_percent_and_speed(monkeypatch, scratch_path) -> None:
    monkeypatch.chdir(scratch_path)
    clock = _fake_clock(monkeypatch)
    screen = _make_screen(["Game A"])

    def body(current: DownloadProgressScreen) -> None:
        current.on_game_start(
            GameStart(game="Game A", source="archive_org", console="gb")
        )
        clock["now"] += 1.0
        current.on_game_bytes(
            GameBytes(game="Game A", downloaded=1363149, total=3000000)
        )
        text = _active_text(current, "Game A")
        assert _SPEED_RE.search(text)
        assert text == "- Game A (45%) | 1.3 MB / 2.9 MB | 1.3 MB/s"
        clock["now"] += 1.0
        current.on_game_bytes(
            GameBytes(game="Game A", downloaded=1823949, total=3000000)
        )
        text = _active_text(current, "Game A")
        assert text == "- Game A (61%) | 1.7 MB / 2.9 MB | 450 KB/s"

    _run(screen, body)


def test_active_row_unknown_total_shows_bytes_placeholder(
    monkeypatch, scratch_path
) -> None:
    monkeypatch.chdir(scratch_path)
    clock = _fake_clock(monkeypatch)
    screen = _make_screen(["Game A"])

    def body(current: DownloadProgressScreen) -> None:
        current.on_game_start(
            GameStart(game="Game A", source="archive_org", console="gb")
        )
        clock["now"] += 1.0
        current.on_game_bytes(GameBytes(game="Game A", downloaded=512000, total=0))
        text = _active_text(current, "Game A")
        assert "? bytes" in text
        assert _SPEED_RE.search(text)

    _run(screen, body)


def test_byte_events_throttled_to_ten_per_second(monkeypatch, scratch_path) -> None:
    monkeypatch.chdir(scratch_path)
    clock = _fake_clock(monkeypatch)
    screen = _make_screen(["Game A"])

    def body(current: DownloadProgressScreen) -> None:
        current.on_game_start(
            GameStart(game="Game A", source="archive_org", console="gb")
        )
        clock["now"] += 1.0
        current.on_game_bytes(
            GameBytes(game="Game A", downloaded=1000000, total=3000000)
        )
        text_before = _active_text(current, "Game A")
        clock["now"] += 0.05
        current.on_game_bytes(
            GameBytes(game="Game A", downloaded=2000000, total=3000000)
        )
        assert _active_text(current, "Game A") == text_before
        clock["now"] += 0.1
        current.on_game_bytes(
            GameBytes(game="Game A", downloaded=2500000, total=3000000)
        )
        assert _active_text(current, "Game A") != text_before

    _run(screen, body)


def test_thousand_rapid_byte_events_no_crash(monkeypatch, scratch_path) -> None:
    monkeypatch.chdir(scratch_path)
    clock = _fake_clock(monkeypatch)
    screen = _make_screen(["Game A"])

    def body(current: DownloadProgressScreen) -> None:
        current.on_game_start(
            GameStart(game="Game A", source="archive_org", console="gb")
        )
        total = 10_000_000
        for index in range(1, 1001):
            clock["now"] += 0.001
            current.on_game_bytes(
                GameBytes(game="Game A", downloaded=index * 10_000, total=total)
            )
        tracking = current._bytes_tracking["Game A"]
        assert tracking["downloaded"] == 10_000_000
        text = _active_text(current, "Game A")
        assert "Game A" in text
        assert current.app.is_running

    _run(screen, body)


def test_torrent_metrics_drive_detailed_row_and_overall_bar(
    monkeypatch, scratch_path
) -> None:
    monkeypatch.chdir(scratch_path)
    screen = _make_screen(["Game A"])

    def body(current: DownloadProgressScreen) -> None:
        current.on_game_start(
            GameStart(game="Game A", source="minerva_torrent", console="gb")
        )
        current.on_game_bytes(
            GameBytes(
                game="Game A",
                downloaded=256 * 1024**2,
                total=1024**3,
                speed_bps=5 * 1024**2,
                eta_seconds=95,
                seeds=11,
                peers=28,
            )
        )

        assert _active_text(current, "Game A") == (
            "- Game A (25%) | 256.0 MB / 1.0 GB | 5.0 MB/s | "
            "ETA 1m 35s | 11 seeds / 28 peers"
        )
        assert round(_percentage(current)) == 25
        assert _header(current).endswith("| 25% transferred")

    _run(screen, body)


def test_active_row_updates_provider_during_fallback(monkeypatch, scratch_path) -> None:
    monkeypatch.chdir(scratch_path)
    screen = _make_screen(["Game A"])

    def body(current: DownloadProgressScreen) -> None:
        current.on_game_start(GameStart(game="Game A", source="first", console="gb"))
        assert _active_text(current, "Game A") == "- Game A via first"
        current.on_game_start(GameStart(game="Game A", source="fallback", console="gb"))
        assert _active_text(current, "Game A") == "- Game A via fallback"
        assert len(current._active) == 1

    _run(screen, body)


def test_item_id_keeps_same_title_rows_distinct_and_renders_stage(
    monkeypatch, scratch_path
) -> None:
    monkeypatch.chdir(scratch_path)
    screen = _make_screen(["Game A", "Game A"])

    def body(current: DownloadProgressScreen) -> None:
        current.on_game_start(GameStart("Game A", "first", "gb", item_id="item-one"))
        current.on_game_start(GameStart("Game A", "second", "gb", item_id="item-two"))
        current.on_game_stage(
            GameStage(
                "Game A",
                "downloading",
                "waiting for peers",
                item_id="item-two",
            )
        )

        assert len(current._active) == 2
        assert _active_text(current, "item-one") == "- Game A via first"
        assert _active_text(current, "item-two") == (
            "- Game A: downloading - waiting for peers"
        )

    _run(screen, body)


def test_report_is_authoritative_and_includes_cancelled(
    monkeypatch, scratch_path
) -> None:
    monkeypatch.chdir(scratch_path)
    screen = _make_screen(["Game A", "Game B"])

    def body(current: DownloadProgressScreen) -> None:
        current.on_game_failed(GameFailed("stale event", "nope"))
        report = RunReport(
            console="gb", attempted=2, acquired=1, failed=0, unverified=0, skipped=0
        )
        setattr(report, "cancelled", 1)
        current.on_download_complete(DownloadComplete(report))

        assert _header(current) == "Overall: 2 / 2 games (0 failed, 1 cancelled)"
        assert _summary(current) == (
            "Cancelled. attempted=2 acquired=1 failed=0 unverified=0 "
            "cancelled=1. Press Esc to return."
        )

    _run(screen, body)


def test_cancelled_event_uses_item_id_and_cancel_copy_requests_acknowledgement(
    monkeypatch, scratch_path
) -> None:
    monkeypatch.chdir(scratch_path)
    screen = _make_screen(["Game A"])

    def body(current: DownloadProgressScreen) -> None:
        current.on_game_start(GameStart("Game A", "source", "gb", item_id="item"))
        current.on_game_cancelled(GameCancelled("Game A", "stopped", item_id="item"))
        assert not current._active
        assert _header(current) == "Overall: 1 / 1 games (0 failed, 1 cancelled)"

        current._stop_event = threading.Event()
        current._cancel_pending = False
        current._on_cancel_decision(True)
        assert current._stop_event.is_set()
        assert _summary(current) == "Cancelling - requesting stop acknowledgement..."

    _run(screen, body)
