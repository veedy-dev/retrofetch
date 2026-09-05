from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from textual.app import App
from textual.message import Message
from textual.widgets import Collapsible, Label, ProgressBar

from retrofetch.orchestrator import RunReport
from retrofetch.tui.downloads import DownloadSession
from retrofetch.tui.messages import (
    DatLoadDone,
    DownloadComplete,
    DownloadCrashed,
    GameBytes,
    GameCancelled,
    GameDone,
    GameFailed,
    GameSkipped,
    GameStage,
    GameStart,
    GameUnverified,
)
from retrofetch.tui.screens.cancel_confirm import CancelConfirmScreen
from retrofetch.tui.screens.download_progress import DownloadProgressScreen
from retrofetch.tui.screens.state import StateScreen


class _ProgressApp(App[None]):
    """An in-memory session host: no download worker or provider access."""

    CSS_PATH = Path(__file__).parents[1] / "retrofetch/tui/styles.tcss"

    def __init__(self, session: DownloadSession, roms_root: Path) -> None:
        super().__init__()
        self.download_session = session
        self.config = SimpleNamespace(roms_root=roms_root)
        self.cancel_requests = 0

    def on_mount(self) -> None:
        self.push_screen(DownloadProgressScreen())

    def cancel_download(self) -> None:
        self.cancel_requests += 1
        self.download_session.cancelling = True
        self.download_session.revision += 1


def _text(screen, selector: str) -> str:
    return "\n".join(
        str(label.content) for label in screen.query(selector).results(Label)
    )


def _progress(screen) -> float:
    return screen.query_one("#progress-overall-bar", ProgressBar).progress


def _run(scratch_path, titles, body, *, dry_run=False) -> None:
    session = DownloadSession({"shortname": "gb"}, titles, dry_run=dry_run)
    app = _ProgressApp(session, scratch_path)

    async def run() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()

            async def emit(*messages: Message) -> None:
                for message in messages:
                    session.apply(message)
                await pilot.pause(0.3)

            await body(app, pilot, emit)

    asyncio.run(run())


def test_terminal_outcomes_count_once_and_complete_progress(scratch_path) -> None:
    async def body(app, pilot, emit):
        await emit(
            GameDone("A", "source", 10, "hash", item_id="a"),
            GameDone("A", "source", 10, "hash", item_id="a"),
            GameUnverified("B", "source", "No DAT", item_id="b"),
            GameFailed("C", "checksum mismatch", item_id="c"),
            GameSkipped("D", "already exists", filename="D.zip", item_id="d"),
            GameCancelled("E", "stopped", item_id="e"),
        )
        assert _progress(app.screen) == 5
        assert _text(app.screen, ".dl-status-row").count("DOWNLOADED: A") == 1
        assert "checksum mismatch" in _text(app.screen, ".status-failed")
        await emit(
            DownloadComplete(
                RunReport(
                    console="gb",
                    attempted=5,
                    acquired=1,
                    unverified=1,
                    failed=1,
                    skipped=1,
                    cancelled=1,
                )
            )
        )
        assert _progress(app.screen) == 5
        assert not app.screen.query(".dl-active-row")
        assert "finished" in _text(app.screen, "#progress-empty").lower()

    _run(scratch_path, list("ABCDE"), body)


def test_same_title_identity_fallback_and_finalization(scratch_path) -> None:
    async def body(app, pilot, emit):
        await emit(
            GameStart("Same title", "first", "gb", item_id="one"),
            GameStart("Same title", "second", "gb", item_id="two"),
            GameStart("Same title", "fallback", "gb", item_id="one"),
            GameStage("Same title", "extracting", "opening archive", item_id="two"),
        )
        assert len(app.screen.query(".dl-active-row")) == 2
        assert "fallback" in _text(app.screen, ".dl-active-metrics")
        assert "Extracting" in _text(app.screen, ".dl-active-metrics")
        await emit(GameDone("Same title", "fallback", 100, None, item_id="one"))
        assert len(app.screen.query(".dl-active-row")) == 1
        assert "second" in _text(app.screen, ".dl-active-metrics")
        assert _progress(app.screen) == 1
        await emit(GameCancelled("Same title", "stopped", item_id="two"))
        assert not app.screen.query(".dl-active-row")
        assert _progress(app.screen) == 2

    _run(scratch_path, ["Same title", "Same title"], body)


def test_bytes_are_cumulative_zero_speed_is_real_and_ready_waits_for_done(
    scratch_path,
) -> None:
    async def body(app, pilot, emit):
        await emit(GameStart("A", "source", "gb"))
        await emit(
            *(GameBytes("A", n * 1024, 1024**2, speed_bps=1024) for n in range(1, 1001))
        )
        assert "1000.0 KB" in _text(app.screen, ".dl-active-metrics")
        await emit(GameBytes("A", 1024**2, 1024**2, speed_bps=0, eta_seconds=0))
        metrics = _text(app.screen, ".dl-active-metrics")
        assert "100%" in metrics and "0 KB/s" in metrics
        assert _progress(app.screen) < 1
        assert not app.screen.query(".dl-status-row")
        await emit(GameStage("A", "verifying", "checking hash"))
        assert "Verifying" in _text(app.screen, ".dl-active-metrics")
        assert _progress(app.screen) < 1
        await emit(GameDone("A", "source", 1024**2, "hash"))
        assert _progress(app.screen) == 1

    _run(scratch_path, ["A"], body)


def test_unknown_total_retains_bytes_and_torrent_metrics(scratch_path) -> None:
    async def body(app, pilot, emit):
        await emit(
            GameStart("A", "torrent", "gb"),
            GameBytes(
                "A",
                256 * 1024**2,
                0,
                speed_bps=5 * 1024**2,
                eta_seconds=95,
                seeds=11,
                peers=28,
            ),
        )
        metrics = _text(app.screen, ".dl-active-metrics")
        assert "256.0 MB" in metrics and "size unknown" in metrics
        assert "5.0 MB/s" in metrics and "ETA 1m 35s" in metrics
        assert "11 seeds / 28 peers" in metrics
        assert "%" not in metrics
        assert _progress(app.screen) == 0
        await emit(GameStart("A", "http", "gb"))
        metrics = _text(app.screen, ".dl-active-metrics")
        assert "http" in metrics and "Starting" in metrics
        assert "0 KB/s" in metrics
        assert "256.0 MB" not in metrics
        assert "ETA" not in metrics and "peers" not in metrics
        assert len(app.screen.query(".dl-active-row")) == 1

    _run(scratch_path, ["A"], body)


def test_missing_dat_is_details_only_but_full_failures_are_primary(
    scratch_path,
) -> None:
    reason = "Permission denied [archive]: " + "long path/" * 20

    async def body(app, pilot, emit):
        await emit(
            DatLoadDone("gb", 0, status="missing", detail="No DAT configured"),
            GameUnverified("A", "source", "No DAT configured"),
            GameFailed("B", reason),
        )
        assert app.screen.query_one("#progress-details", Collapsible).collapsed
        assert "No DAT configured" not in _text(
            app.screen, "#summary-line, .dl-status-row"
        )
        assert reason in _text(app.screen, ".status-failed")
        await pilot.press("v")
        assert not app.screen.query_one("#progress-details", Collapsible).collapsed
        assert "No DAT configured" in _text(app.screen, "#progress-detail-text")
        await emit(DownloadCrashed("disk unavailable [device]"))
        assert "disk unavailable [device]" in _text(app.screen, "#summary-line")

    _run(scratch_path, ["A", "B"], body)


def test_back_keeps_session_reopen_updates_and_cancel_requires_confirmation(
    scratch_path,
) -> None:
    async def body(app, pilot, emit):
        await emit(GameStart("A", "source", "gb"))
        await pilot.press("escape")
        assert not isinstance(app.screen, DownloadProgressScreen)
        assert app.download_session.running and app.cancel_requests == 0
        await emit(GameDone("A", "source", 10, None))
        await app.push_screen(DownloadProgressScreen())
        await pilot.pause()
        assert "DOWNLOADED: A" in _text(app.screen, ".dl-status-row")
        assert not app.screen.query(".dl-active-row")
        await pilot.press("h")
        assert isinstance(app.screen, StateScreen)
        await pilot.press("escape", "c")
        assert isinstance(app.screen, CancelConfirmScreen)
        await pilot.press("escape")
        assert app.cancel_requests == 0
        await pilot.press("c", "y")
        await pilot.pause(0.3)
        assert app.cancel_requests == 1 and app.download_session.running
        assert "stop" in _text(app.screen, "#progress-empty").lower()
        await pilot.press("h")
        assert isinstance(app.screen, StateScreen)
        await emit(
            DownloadComplete(RunReport("gb", attempted=2, acquired=1, cancelled=1))
        )
        assert app.download_session.unread
        await pilot.press("escape")
        await pilot.pause(0.3)
        assert isinstance(app.screen, DownloadProgressScreen)
        assert not app.download_session.unread
        await pilot.press("escape")
        assert app.cancel_requests == 1

    _run(scratch_path, ["A", "B"], body)


def test_authoritative_report_and_dry_run_never_claim_downloaded(scratch_path) -> None:
    async def body(app, pilot, emit):
        await emit(GameDone("A", "dry-run", 0, None))
        assert "DRY-RUN: A" in _text(app.screen, ".dl-status-row")
        assert "DOWNLOADED:" not in _text(app.screen, ".dl-status-row")
        await emit(
            DownloadComplete(
                RunReport(
                    console="gb",
                    attempted=2,
                    acquired=0,
                    unverified=0,
                    failed=0,
                    skipped=0,
                    cancelled=0,
                )
            )
        )
        assert _progress(app.screen) == 2

    _run(scratch_path, ["A", "B"], body, dry_run=True)
