from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from queue import Queue

import pytest
from textual.widgets import OptionList

import retrofetch.tui.workers.download_worker as downloads
from retrofetch.config import Config, ConsoleOverride
from retrofetch.events import (
    GameBytesEvent,
    GameCancelledEvent,
    GameDoneEvent,
    GameFailedEvent,
    GameSkippedEvent,
    GameStartEvent,
    GameUnverifiedEvent,
)
from retrofetch.orchestrator import RunReport
from retrofetch.tui.app import RetrofetchApp
from retrofetch.tui.messages import DownloadUpdate, GameDone
from retrofetch.tui.screens.cancel_confirm import CancelConfirmScreen
from retrofetch.tui.screens.download_confirm import DownloadConfirmScreen
from retrofetch.tui.screens.download_progress import DownloadProgressScreen

CONSOLE = {"shortname": "nes", "name": "NES", "class": "A"}


class DownloadApp(RetrofetchApp):
    CSS_PATH = Path(__file__).parents[1] / "retrofetch/tui/styles.tcss"

    def _open_fresh_home(self) -> None:
        self.push_screen(
            DownloadConfirmScreen(console_entry=CONSOLE, override=self.overrides["nes"])
        )


def make_app(tmp_path, titles):
    return DownloadApp(
        config=Config(
            roms_root=tmp_path / "roms",
            cache_dir=tmp_path / "cache",
            log_file=tmp_path / "log",
        ),
        config_path=tmp_path / "config.yml",
        consoles_yml={"consoles": [CONSOLE]},
        overrides={
            "nes": ConsoleOverride(include=titles, limit=12, region_priority=["Japan"])
        },
    )


async def until(pilot, predicate):
    for _ in range(150):
        if predicate():
            return
        await pilot.pause(0.01)
    assert predicate(), "background transition did not complete"


def test_navigation_hidden_events_queue_reconciliation_and_late_packets(
    monkeypatch, tmp_path
):
    commands = Queue()
    calls = []
    cleanup = threading.Event()

    def run_console(**kwargs):
        calls.append(threading.get_ident())
        bus = kwargs["event_bus"]
        while True:
            event = commands.get(timeout=10)
            if isinstance(event, RunReport):
                assert cleanup.wait(10)
                return event
            bus.publish(event)

    monkeypatch.setattr(downloads, "run_console", run_console)

    async def run():
        app = make_app(tmp_path, ["Good", "Unknown", "Present", "Bad", "No artifact"])
        async with app.run_test(size=(100, 32)) as pilot:
            assert app.start_download(CONSOLE, list(app.overrides["nes"].include))
            session = app.download_session
            assert session is not None
            assert app._download_worker is not None
            assert app._stop_event is not None
            app.action_downloads()
            await pilot.pause()
            commands.put(GameStartEvent("Good", "archive", "nes", "good"))
            await until(pilot, lambda: "good" in session.active)
            await pilot.press("escape")
            assert isinstance(app.screen, DownloadConfirmScreen)
            commands.put(GameBytesEvent("Good", 100, 100, "good", speed_bps=2048))
            await until(pilot, lambda: session.active["good"].downloaded == 100)
            assert session.progress == 0
            assert not app._stop_event.is_set()
            assert not app.start_download(CONSOLE, ["Bad"])
            commands.put(GameDoneEvent("Good", "archive", 100, "sha", "good"))
            commands.put(GameUnverifiedEvent("Unknown", "archive", "No DAT", "unknown"))
            commands.put(
                GameSkippedEvent(
                    "Present", "already acquired", "present.zip", "present"
                )
            )
            commands.put(GameFailedEvent("Bad", "hash mismatch", "bad"))
            commands.put(
                GameSkippedEvent("No artifact", "not available", item_id="absent")
            )
            await until(pilot, lambda: session.processed_count == 5)
            assert app.overrides["nes"].include == ["Bad", "No artifact"]
            assert app.overrides["nes"].limit == 12
            assert app.overrides["nes"].region_priority == ["Japan"]
            assert app.screen.query_one(OptionList).option_count == 2
            await pilot.press("f6", "f6")
            assert isinstance(app.screen, DownloadProgressScreen)
            assert (
                sum(
                    isinstance(screen, DownloadProgressScreen)
                    for screen in app.screen_stack
                )
                == 1
            )
            assert len(calls) == 1 and calls[0] != threading.get_ident()
            await pilot.press("escape")
            commands.put(
                RunReport(
                    "nes", attempted=5, acquired=1, unverified=1, skipped=2, failed=1
                )
            )
            assert not app._download_worker.finished.is_set()
            cleanup.set()
            await until(pilot, lambda: not session.running)
            assert app._download_worker.finished.is_set()
            assert session.unread
            assert any("hash mismatch" in record.detail for record in session.recent)
            assert app.start_download(CONSOLE, ["Bad"], dry_run=True)
            next_session = app.download_session
            assert next_session is not None
            app.post_message(
                DownloadUpdate(session, GameDone("Bad", "archive", 1, "sha", "late"))
            )
            commands.put(GameDoneEvent("Bad", "dry-run", 0, None, "dry"))
            commands.put(RunReport("nes", attempted=1))
            await until(pilot, lambda: not next_session.running)
            assert app.overrides["nes"].include == ["Bad", "No artifact"]
            assert next_session.acquired == 0
            assert next_session.processed_count == 1
            assert next_session.recent[0].outcome == "dry-run"

    try:
        asyncio.run(run())
    finally:
        cleanup.set()
        commands.put(RunReport("nes"))


@pytest.mark.parametrize("quit_key", [None, "ctrl+c"])
def test_cooperative_stop_waits_for_real_cleanup(monkeypatch, tmp_path, quit_key):
    entered = threading.Event()
    stopping = threading.Event()
    cleanup = threading.Event()

    def run_console(**kwargs):
        entered.set()
        assert kwargs["stop_event"].wait(10)
        stopping.set()
        assert cleanup.wait(10)
        kwargs["event_bus"].publish(GameCancelledEvent("Game", "user stopped", "game"))
        return RunReport("nes", attempted=1, cancelled=1)

    monkeypatch.setattr(downloads, "run_console", run_console)

    async def run():
        app = make_app(tmp_path, ["Game"])
        async with app.run_test(size=(100, 32)) as pilot:
            assert app.start_download(CONSOLE, ["Game"])
            assert app._download_worker is not None
            session = app.download_session
            assert session is not None
            await until(pilot, entered.is_set)
            app.action_downloads()
            await pilot.pause()
            await pilot.press(quit_key or "c")
            assert isinstance(app.screen, CancelConfirmScreen)
            await pilot.press("n")
            assert not stopping.is_set()
            await pilot.press(quit_key or "c", "y")
            await until(pilot, stopping.is_set)
            assert app.is_running
            assert not app._download_worker.finished.is_set()
            assert not app.start_download(CONSOLE, ["Game"])
            assert session.running
            cleanup.set()
            if quit_key:
                await until(pilot, lambda: app.return_value == 0)
            else:
                await until(pilot, lambda: not session.running)
                assert session.cancelled == 1
                assert not session.unread
            assert app._download_worker.finished.is_set()
            assert app.overrides["nes"].include == ["Game"]

    try:
        asyncio.run(run())
    finally:
        cleanup.set()


def test_setup_gate_declines_on_cancel_and_completion_follows_unsubscribe(
    monkeypatch, tmp_path
):
    received = []
    entered = threading.Event()
    result = []

    def run_console(**kwargs):
        entered.set()
        result.append(kwargs["torrent_setup_callback"]())
        return RunReport("nes", cancelled=1)

    monkeypatch.setattr(downloads, "run_console", run_console)
    worker = downloads.DownloadWorker(received.append)
    stop = worker.start(
        console_entry=CONSOLE,
        wantlist=["Game"],
        config=Config(roms_root=tmp_path),
        allow_torrent=True,
        consoles_yml={},
    )
    bus = worker._bus
    assert bus is not None
    thread = threading.Thread(target=worker.run)
    thread.start()
    try:
        assert entered.wait(5)
        stop.set()
        thread.join(5)
        assert not thread.is_alive()
        assert result == [False]
        assert worker.finished.is_set()
        before = len(received)
        bus.publish(GameDoneEvent("late", "archive", 1, "sha"))
        assert len(received) == before
        assert isinstance(received[-1], downloads.DownloadComplete)
    finally:
        stop.set()
        thread.join(5)


def test_app_owns_setup_gate_and_reports_crash_after_cleanup(monkeypatch, tmp_path):
    from retrofetch.tui.screens.torrent_setup import TorrentSetupScreen

    def run_console(**kwargs):
        assert kwargs["torrent_setup_callback"]() is False
        raise RuntimeError("provider connection failed")

    monkeypatch.setattr(downloads, "run_console", run_console)

    async def run():
        app = make_app(tmp_path, ["Game"])
        async with app.run_test(size=(100, 32)) as pilot:
            assert app.start_download(CONSOLE, ["Game"])
            session = app.download_session
            assert session is not None
            await until(pilot, lambda: isinstance(app.screen, TorrentSetupScreen))
            assert app._setup_request is not None
            app.cancel_download()
            await until(pilot, lambda: not session.running)
            assert app._setup_request is None
            assert session.error == "provider connection failed"
            assert app.overrides["nes"].include == ["Game"]
            assert app._download_worker is not None
            assert app._download_worker.finished.is_set()

    asyncio.run(run())


def test_real_dry_run_keeps_reviewed_progress_without_downloads(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    async def run():
        titles = ["Fixture Alpha", "Fixture Beta"]
        app = make_app(tmp_path, titles)
        app.config.source_fallback_by_class = {}
        app.config.torrent_mode = "disabled"
        async with app.run_test(size=(100, 32)) as pilot:
            assert app.start_download(CONSOLE, titles, dry_run=True)
            session = app.download_session
            assert session is not None
            await until(pilot, lambda: not session.running)
            assert session.error is None
            assert session.processed_count == 2
            assert session.progress == 2
            assert session.acquired == session.unverified == 0
            assert all(record.outcome == "dry-run" for record in session.recent)
            assert app.overrides["nes"].include == titles
            assert list((tmp_path / "roms" / "nes").iterdir()) == []

    asyncio.run(run())


def test_native_notifications_render_provider_errors_literally(tmp_path):
    async def run():
        app = make_app(tmp_path, [])
        async with app.run_test(size=(80, 24), notifications=True) as pilot:
            app.show_toast("Provider returned [/untrusted]", "error")
            await pilot.pause()
            assert "[/untrusted]" in app.export_screenshot()

    asyncio.run(run())
