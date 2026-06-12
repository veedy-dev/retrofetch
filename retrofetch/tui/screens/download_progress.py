"""Download progress screen: overall ProgressBar + active list + completed log + summary."""
from __future__ import annotations

import threading
from time import monotonic
from typing import Any

from textual.app import ComposeResult  # pyright: ignore[reportMissingImports]
from textual.binding import Binding  # pyright: ignore[reportMissingImports]
from textual.containers import ScrollableContainer, Vertical  # pyright: ignore[reportMissingImports]
from textual.screen import Screen  # pyright: ignore[reportMissingImports]
from textual.widgets import Footer, Header, Label, ProgressBar, Static  # pyright: ignore[reportMissingImports]

from retrofetch.tui.messages import (
    CloudflareBlock,
    DatLoadDone,
    DatLoadStart,
    DownloadComplete,
    DownloadCrashed,
    ExtractionDone,
    ExtractionStart,
    GameBytes,
    GameDone,
    GameFailed,
    GameSkipped,
    GameStart,
    GameUnverified,
    RateLimit,
    SourceDead,
)
from retrofetch.tui.screens.cancel_confirm import CancelConfirmScreen
from retrofetch.tui.workers.download_worker import DownloadWorker

_MAX_ACTIVE_ROWS = 3
_MAX_COMPLETED_ROWS = 50
_MIN_SPEED_INTERVAL = 0.1
_MIN_LABEL_INTERVAL = 0.1


def _format_speed(bps: float) -> str:
    if bps >= 1024 * 1024:
        return f"{bps / (1024 * 1024):.1f} MB/s"
    return f"{bps / 1024:.0f} KB/s"


class DownloadProgressScreen(Screen[None]):
    BINDINGS = [
        Binding("escape", "request_cancel", "Cancel", show=True),
        Binding("c", "request_cancel", "Cancel", show=True),
    ]

    def __init__(
        self,
        *,
        console_entry: dict[str, Any],
        wantlist: list[str],
        dry_run: bool,
    ) -> None:
        super().__init__()
        self.console_entry = console_entry
        self.shortname = str(console_entry.get("shortname", "?"))
        self.wantlist = list(wantlist)
        self.dry_run = bool(dry_run)
        self._active: dict[str, Label] = {}
        self._bytes_tracking: dict[str, dict[str, float]] = {}
        self._acquired: int = 0
        self._failed: int = 0
        self._skipped: int = 0
        self._unverified: int = 0
        self._worker: DownloadWorker | None = None
        self._stop_event: threading.Event | None = None
        self._cancel_pending: bool = False
        self._summary_complete: bool = False

    def compose(self) -> ComposeResult:
        total = len(self.wantlist)
        yield Header(show_clock=False)
        with Vertical(id="main-panel"):
            yield Label(
                f"Downloading: {self.shortname} - {total} games. Esc/c=cancel.",
                id="dl-title",
            )
            with Vertical(id="progress-overall"):
                yield Label(f"Overall: 0 / {total} games (0 failed)", id="progress-overall-text")
                yield ProgressBar(
                    total=max(total, 1),
                    show_eta=False,
                    show_percentage=True,
                    id="progress-overall-bar",
                )
            yield Static("Active downloads:", classes="dl-section-title")
            yield Vertical(id="progress-active")
            yield Static("Recently completed:", classes="dl-section-title")
            yield ScrollableContainer(id="progress-completed")
            yield Label("", id="summary-line")
        yield Footer()

    def on_mount(self) -> None:
        self._worker = DownloadWorker(self)
        self._stop_event = self._worker.start(
            console_entry=self.console_entry,
            wantlist=self.wantlist,
            config=self.app.config,  # pyright: ignore[reportAttributeAccessIssue]
            allow_torrent=True,
            consoles_yml=self.app.consoles_yml,  # pyright: ignore[reportAttributeAccessIssue]
            dry_run=self.dry_run,
        )
        self.run_worker(self._worker.run, thread=True, exclusive=True, group="download")

    def _attempted(self) -> int:
        return self._acquired + self._failed + self._unverified + self._skipped

    def _bump_overall(self) -> None:
        total = max(len(self.wantlist), 1)
        self.query_one("#progress-overall-text", Label).update(
            f"Overall: {self._acquired} / {len(self.wantlist)} games ({self._failed} failed)"
        )
        self.query_one("#progress-overall-bar", ProgressBar).update(
            progress=min(self._acquired, total),
            total=total,
        )

    def _trim_completed(self) -> None:
        completed = self.query_one("#progress-completed", ScrollableContainer)
        children = list(completed.children)
        if len(children) > _MAX_COMPLETED_ROWS:
            for child in children[: len(children) - _MAX_COMPLETED_ROWS]:
                child.remove()

    def _drop_active(self, game: str) -> None:
        self._bytes_tracking.pop(game, None)
        label = self._active.pop(game, None)
        if label is not None:
            label.remove()

    def _new_tracking(self) -> dict[str, float]:
        return {
            "downloaded": 0.0,
            "speed_bps": 0.0,
            "last_update": 0.0,
            "last_bytes": 0.0,
            "last_ts": monotonic(),
        }

    def on_game_start(self, message: GameStart) -> None:
        if message.game in self._active:
            return
        if len(self._active) >= _MAX_ACTIVE_ROWS:
            return
        active = self.query_one("#progress-active", Vertical)
        prefix = "DRY RUN" if message.source == "dry-run" else message.source
        label = Label(f"- [{prefix}] {message.game}", classes="dl-active-row")
        active.mount(label)
        self._active[message.game] = label
        self._bytes_tracking[message.game] = self._new_tracking()

    def on_game_bytes(self, message: GameBytes) -> None:
        label = self._active.get(message.game)
        if label is None:
            return
        tracking = self._bytes_tracking.setdefault(message.game, self._new_tracking())
        now = monotonic()
        tracking["downloaded"] = float(message.downloaded)
        elapsed = now - tracking["last_ts"]
        if elapsed >= _MIN_SPEED_INTERVAL:
            delta = float(message.downloaded) - tracking["last_bytes"]
            tracking["speed_bps"] = max(delta, 0.0) / elapsed
            tracking["last_bytes"] = float(message.downloaded)
            tracking["last_ts"] = now
        if now - tracking["last_update"] < _MIN_LABEL_INTERVAL:
            return
        tracking["last_update"] = now
        speed = _format_speed(tracking["speed_bps"])
        if not message.total or message.total <= 0:
            label.update(f"- {message.game} (? bytes) {speed}")
            return
        pct = max(0.0, min(100.0, 100.0 * message.downloaded / message.total))
        label.update(f"- {message.game} ({pct:.0f}%) {speed}")

    def on_game_done(self, message: GameDone) -> None:
        self._acquired += 1
        self._drop_active(message.game)
        completed = self.query_one("#progress-completed", ScrollableContainer)
        if message.source == "dry-run":
            completed.mount(Label(f"DRY RUN: {message.game}", classes="status-unverified dl-status-row"))
        else:
            completed.mount(
                Label(f"OK: {message.game} ({message.size} bytes)", classes="status-acquired dl-status-row")
            )
        self._trim_completed()
        self._bump_overall()

    def on_game_failed(self, message: GameFailed) -> None:
        self._failed += 1
        self._drop_active(message.game)
        completed = self.query_one("#progress-completed", ScrollableContainer)
        completed.mount(
            Label(f"[X] {message.game}: {message.reason}", classes="status-failed dl-status-row")
        )
        self._trim_completed()
        self._bump_overall()

    def on_game_skipped(self, message: GameSkipped) -> None:
        self._skipped += 1
        self._drop_active(message.game)
        completed = self.query_one("#progress-completed", ScrollableContainer)
        completed.mount(
            Label(
                f"SKIP: {message.game}: {message.reason}",
                classes="status-unverified dl-status-row",
            )
        )
        self._trim_completed()
        self._bump_overall()

    def on_game_unverified(self, message: GameUnverified) -> None:
        self._unverified += 1
        self._drop_active(message.game)
        completed = self.query_one("#progress-completed", ScrollableContainer)
        reason = f": {message.reason}" if message.reason else ""
        completed.mount(
            Label(
                f"~ {message.game}{reason}",
                classes="status-unverified dl-status-row",
            )
        )
        self._trim_completed()
        self._bump_overall()

    def on_source_dead(self, message: SourceDead) -> None:
        completed = self.query_one("#progress-completed", ScrollableContainer)
        completed.mount(
            Label(
                f"[!] Source dead: {message.source} - {message.reason}",
                classes="status-unverified dl-status-row",
            )
        )
        self._trim_completed()

    def on_rate_limit(self, message: RateLimit) -> None:
        completed = self.query_one("#progress-completed", ScrollableContainer)
        completed.mount(
            Label(
                f"[!] Rate limited on {message.source} (retry after {message.retry_after}s)",
                classes="status-unverified dl-status-row",
            )
        )
        self._trim_completed()

    def on_cloudflare_block(self, message: CloudflareBlock) -> None:
        completed = self.query_one("#progress-completed", ScrollableContainer)
        completed.mount(
            Label(
                f"[!] Cloudflare block on {message.source} (status={message.status})",
                classes="status-unverified dl-status-row",
            )
        )
        self._trim_completed()

    def on_dat_load_start(self, message: DatLoadStart) -> None:
        self.query_one("#summary-line", Label).update(
            f"Loading DAT for {message.console}: {message.dat_name}..."
        )

    def on_dat_load_done(self, message: DatLoadDone) -> None:
        if message.detail:
            self.query_one("#summary-line", Label).update(message.detail)
            return
        self.query_one("#summary-line", Label).update(
            f"DAT loaded: {message.games_loaded} games. Starting downloads..."
        )

    def on_extraction_start(self, message: ExtractionStart) -> None:
        completed = self.query_one("#progress-completed", ScrollableContainer)
        completed.mount(
            Label(
                f"... Extracting {message.filename} ({message.format})",
                classes="status-unverified dl-status-row",
            )
        )
        self._trim_completed()

    def on_extraction_done(self, message: ExtractionDone) -> None:
        completed = self.query_one("#progress-completed", ScrollableContainer)
        completed.mount(
            Label(
                f"... Extracted to {message.extracted_to}",
                classes="status-acquired dl-status-row",
            )
        )
        self._trim_completed()

    def on_download_complete(self, message: DownloadComplete) -> None:
        self._bump_overall()
        attempted = self._attempted()
        if self.dry_run:
            summary = f"Dry run done. attempted={attempted}. No files downloaded. Press Esc to return."
        else:
            summary = (
                f"Done. attempted={attempted} acquired={self._acquired} "
                f"failed={self._failed} unverified={self._unverified}"
                f"{f' skipped={self._skipped}' if self._skipped else ''}. Press Esc to return."
            )
        self.query_one("#summary-line", Label).update(summary)
        self._summary_complete = True

    def on_download_crashed(self, message: DownloadCrashed) -> None:
        self.query_one("#summary-line", Label).update(
            f"CRASHED: {message.exc}. Press Esc to return."
        )
        self._summary_complete = True

    def action_request_cancel(self) -> None:
        if (
            self._summary_complete
            or self._stop_event is None
            or self._stop_event.is_set()
        ):
            self.dismiss(None)
            return
        self.app.push_screen(
            CancelConfirmScreen(
                prompt=f"Cancel running download for {self.shortname}? (y/n)"
            ),
            self._on_cancel_decision,
        )

    def _on_cancel_decision(self, result: bool | None) -> None:
        if result is True:
            if self._stop_event is not None:
                self._stop_event.set()
            self._cancel_pending = True
            self.query_one("#summary-line", Label).update(
                "Cancelling - waiting for current download to finish..."
            )
