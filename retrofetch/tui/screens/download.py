"""Download screen with live per-file progress bars.

Pushed from HomeScreen when the user presses 'd' on a selected Class A/B/C console.
Wires an EventBus → DownloadWorker → DownloadComplete/DownloadCrashed message flow.
"""
from __future__ import annotations

import threading
from typing import Any

from textual.app import ComposeResult  # pyright: ignore[reportMissingImports]
from textual.binding import Binding  # pyright: ignore[reportMissingImports]
from textual.containers import ScrollableContainer, Vertical  # pyright: ignore[reportMissingImports]
from textual.screen import Screen  # pyright: ignore[reportMissingImports]
from textual.widgets import Checkbox, Footer, Header, Label, ProgressBar, Static  # pyright: ignore[reportMissingImports]

from retrofetch.config import ConsoleOverride
from retrofetch.ranker import get_wantlist
from retrofetch.tui.messages import (
    DownloadComplete,
    DownloadCrashed,
    GameBytes,
    GameDone,
    GameFailed,
    GameStart,
    CloudflareBlock,
    SourceDead,
)
from retrofetch.tui.workers.download_worker import DownloadWorker


class DownloadScreen(Screen[None]):
    BINDINGS = [
        Binding("enter", "start", "Start", show=True),
        Binding("c", "cancel", "Cancel", show=True),
        Binding("escape", "back", "Back", show=True),
    ]

    def __init__(
        self,
        *,
        console_entry: dict[str, Any],
        override: ConsoleOverride | None,
    ) -> None:
        super().__init__()
        self.console_entry = console_entry
        self.shortname = str(console_entry.get("shortname", "?"))
        self.override = override
        self._bars: dict[str, ProgressBar] = {}
        self._labels: dict[str, Label] = {}
        self._wantlist: list[str] = []
        self._worker: DownloadWorker | None = None
        self._stop_event: threading.Event | None = None
        self._started: bool = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Vertical(id="main-panel"):
            yield Label(
                f"Download: {self.shortname}. Enter=start, c=cancel, esc=back.",
                id="dl-title",
            )
            yield Checkbox(
                "Dry run (no real downloads)",
                id="dry-run-toggle",
                value=self.app.config.dry_run,  # pyright: ignore[reportAttributeAccessIssue]
            )
            yield Label("", id="summary-line")
            yield ScrollableContainer(id="progress-list")
        yield Footer()

    def on_mount(self) -> None:
        try:
            self._wantlist = get_wantlist(
                console_entry=self.console_entry,
                overrides=self.override,
                config=self.app.config,  # pyright: ignore[reportAttributeAccessIssue]
                limit=self.override.limit if (self.override and self.override.limit) else self.app.config.default_limit,  # pyright: ignore[reportAttributeAccessIssue]
            )
        except Exception as exc:
            self._wantlist = []
            self.query_one("#summary-line", Label).update(f"wantlist error: {exc}")
            return
        self.query_one("#summary-line", Label).update(
            f"Ready to download {len(self._wantlist)} games. Press Enter to start."
        )

    def action_start(self) -> None:
        if self._started:
            return
        self._started = True
        # snapshot dry-run state at start
        dry = self.query_one("#dry-run-toggle", Checkbox).value
        # update app.config so other screens respect this (per T10 design)
        self.app.config.dry_run = bool(dry)  # pyright: ignore[reportAttributeAccessIssue]
        self._worker = DownloadWorker(self)
        self._stop_event = self._worker.start(
            console_entry=self.console_entry,
            wantlist=self._wantlist,
            config=self.app.config,  # pyright: ignore[reportAttributeAccessIssue]
            allow_torrent=True,
            consoles_yml=self.app.consoles_yml,  # pyright: ignore[reportAttributeAccessIssue]
            dry_run=bool(dry),
        )
        self.run_worker(self._worker.run, thread=True, exclusive=True, group="download")
        self.query_one("#summary-line", Label).update(
            f"Started ({'dry-run' if dry else 'live'}): {len(self._wantlist)} games."
        )

    def action_cancel(self) -> None:
        if self._stop_event is not None:
            self._stop_event.set()
        self.query_one("#summary-line", Label).update("Cancelled. Press esc to return.")

    def action_back(self) -> None:
        # Leave the screen; any in-flight worker will still wind down via stop_event if set
        self.dismiss(None)

    # --- Message handlers -------------------------------------------------

    def _ensure_bar(self, game: str) -> ProgressBar:
        if game not in self._bars:
            container = self.query_one("#progress-list", ScrollableContainer)
            label = Label(f"- {game}", classes="dl-label")
            bar = ProgressBar(total=100, show_eta=False, show_percentage=True)
            container.mount(label)
            container.mount(bar)
            self._labels[game] = label
            self._bars[game] = bar
        return self._bars[game]

    def on_game_start(self, message: GameStart) -> None:
        bar = self._ensure_bar(message.game)
        bar.update(total=100, progress=0)
        badge = "dry-run" if message.source == "dry-run" else message.source
        self._labels[message.game].update(f"- [{badge}] {message.game}")

    def on_game_bytes(self, message: GameBytes) -> None:
        bar = self._ensure_bar(message.game)
        total = max(message.total, 1)
        # Normalize to 0-100 scale
        pct = max(0.0, min(100.0, 100.0 * message.downloaded / total))
        bar.update(total=100, progress=pct)

    def on_game_done(self, message: GameDone) -> None:
        bar = self._ensure_bar(message.game)
        bar.update(total=100, progress=100)
        label = self._labels[message.game]
        label.update(f"- [OK] {message.game} ({message.size} bytes)")
        label.add_class("status-acquired")

    def on_game_failed(self, message: GameFailed) -> None:
        bar = self._ensure_bar(message.game)
        bar.update(total=100, progress=100)
        label = self._labels[message.game]
        label.update(f"- [X] {message.game}: {message.reason}")
        label.add_class("status-failed")

    def on_source_dead(self, message: SourceDead) -> None:
        container = self.query_one("#progress-list", ScrollableContainer)
        warn = Static(f"[!] Source dead: {message.source} - {message.reason}", classes="status-unverified")
        container.mount(warn)

    def on_cloudflare_block(self, message: CloudflareBlock) -> None:
        container = self.query_one("#progress-list", ScrollableContainer)
        warn = Static(f"[!] Cloudflare block on {message.source} (status={message.status})", classes="status-unverified")
        container.mount(warn)

    def on_download_complete(self, message: DownloadComplete) -> None:
        r = message.report
        self.query_one("#summary-line", Label).update(
            f"Done. attempted={r.attempted} acquired={r.acquired} failed={r.failed} unverified={r.unverified}. "
            "Press esc to return."
        )

    def on_download_crashed(self, message: DownloadCrashed) -> None:
        self.query_one("#summary-line", Label).update(
            f"CRASHED: {message.exc}. Press esc to return."
        )
