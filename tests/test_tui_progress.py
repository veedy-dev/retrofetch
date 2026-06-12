from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any

from textual.app import App, ComposeResult

from retrofetch.config import Config
from retrofetch.orchestrator import RunReport
from retrofetch.tui.messages import DownloadComplete, GameDone, GameFailed
from retrofetch.tui.screens.download_progress import DownloadProgressScreen


class _DummyWorker:
    def __init__(self, screen: DownloadProgressScreen) -> None:
        self.screen = screen

    def start(self, **kwargs: Any) -> threading.Event:
        return threading.Event()

    def run(self) -> None:
        return None


class _ProgressApp(App[None]):
    def __init__(self, screen: DownloadProgressScreen) -> None:
        super().__init__()
        self.screen_to_push = screen
        self.config = Config(roms_root=Path("ROMs"))
        self.consoles_yml = {"consoles": []}

    def compose(self) -> ComposeResult:
        yield self.screen_to_push


def _label_text(screen: DownloadProgressScreen) -> str:
    label = screen.query_one("#progress-overall-text")
    return str(getattr(label, "content", ""))


def test_all_fail_run_shows_zero_percent(monkeypatch) -> None:
    monkeypatch.setattr(
        "retrofetch.tui.screens.download_progress.DownloadWorker",
        _DummyWorker,
    )
    screen = DownloadProgressScreen(
        console_entry={"shortname": "psp"},
        wantlist=[f"Game {i}" for i in range(7)],
        dry_run=False,
    )
    app = _ProgressApp(screen)

    async def run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            for i in range(7):
                screen.on_game_failed(GameFailed(f"Game {i}", "failed"))
            screen.on_download_complete(
                DownloadComplete(RunReport(console="psp", attempted=7, failed=7))
            )
            await pilot.pause()
            bar = screen.query_one("#progress-overall-bar")
            assert getattr(bar, "progress") == 0
            assert "Overall: 0 / 7 games (7 failed)" in _label_text(screen)

    asyncio.run(run())


def test_mixed_success_renders_proportionally(monkeypatch) -> None:
    monkeypatch.setattr(
        "retrofetch.tui.screens.download_progress.DownloadWorker",
        _DummyWorker,
    )
    screen = DownloadProgressScreen(
        console_entry={"shortname": "psp"},
        wantlist=[f"Game {i}" for i in range(7)],
        dry_run=False,
    )
    app = _ProgressApp(screen)

    async def run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            for i in range(3):
                screen.on_game_done(GameDone(f"Game {i}", "source", 100, None))
            for i in range(3, 7):
                screen.on_game_failed(GameFailed(f"Game {i}", "failed"))
            screen.on_download_complete(
                DownloadComplete(
                    RunReport(console="psp", attempted=7, acquired=3, failed=4)
                )
            )
            await pilot.pause()
            bar = screen.query_one("#progress-overall-bar")
            assert getattr(bar, "progress") == 3
            assert getattr(bar, "total") == 7
            assert "Overall: 3 / 7 games (4 failed)" in _label_text(screen)

    asyncio.run(run())
