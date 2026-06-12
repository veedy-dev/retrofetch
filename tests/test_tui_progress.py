from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from textual.app import App
from textual.widgets import Label, ProgressBar

from retrofetch.orchestrator import RunReport
from retrofetch.tui.messages import DownloadComplete, GameDone, GameFailed
from retrofetch.tui.screens.download_progress import DownloadProgressScreen


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


def test_all_fail_progress_stays_at_zero(monkeypatch, scratch_path) -> None:
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
                RunReport(console="gb", attempted=7, acquired=0, failed=7, unverified=0, skipped=0)
            )
        )
        assert round(_percentage(current)) == 0
        assert _header(current) == "Overall: 0 / 7 games (7 failed)"
        assert _summary(current) == (
            "Done. attempted=7 acquired=0 failed=7 unverified=0. Press Esc to return."
        )

    _run(screen, body)


def test_mixed_progress_tracks_successes_only(monkeypatch, scratch_path) -> None:
    monkeypatch.chdir(scratch_path)
    screen = _TestProgressScreen(
        console_entry={"shortname": "gb", "class": "A"},
        wantlist=[f"Game {index}" for index in range(7)],
        dry_run=False,
    )

    def body(current: DownloadProgressScreen) -> None:
        for index in range(3):
            current.on_game_done(
                GameDone(game=f"Game {index}", source="archive_org", size=123, sha1=None)
            )
        for index in range(3, 7):
            current.on_game_failed(GameFailed(game=f"Game {index}", reason="nope"))
        current.on_download_complete(
            DownloadComplete(
                RunReport(console="gb", attempted=7, acquired=3, failed=4, unverified=0, skipped=0)
            )
        )
        assert round(_percentage(current)) == 43
        assert _header(current) == "Overall: 3 / 7 games (4 failed)"
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
                GameDone(game=f"Game {index}", source="archive_org", size=123, sha1=None)
            )
        current.on_download_complete(
            DownloadComplete(
                RunReport(console="gb", attempted=5, acquired=5, failed=0, unverified=0, skipped=0)
            )
        )
        assert round(_percentage(current)) == 100
        assert _header(current) == "Overall: 5 / 5 games (0 failed)"

    _run(screen, body)



