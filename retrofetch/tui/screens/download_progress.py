"""A reopenable view of the app-owned download session."""

from __future__ import annotations

from textual.app import ComposeResult  # pyright: ignore[reportMissingImports]
from textual.binding import Binding  # pyright: ignore[reportMissingImports]
from textual.containers import (  # pyright: ignore[reportMissingImports]
    ScrollableContainer,
    Vertical,
)
from textual.screen import Screen  # pyright: ignore[reportMissingImports]
from textual.timer import Timer  # pyright: ignore[reportMissingImports]
from textual.widgets import (  # pyright: ignore[reportMissingImports]
    Collapsible,
    Footer,
    Header,
    Label,
    ProgressBar,
    Static,
)

from retrofetch.tui.downloads import (
    DownloadSession,
    format_bytes,
    format_eta,
    format_speed,
)
from retrofetch.tui.screens.cancel_confirm import CancelConfirmScreen
from retrofetch.tui.screens.state import StateScreen


class DownloadProgressScreen(Screen[None]):
    BINDINGS = [
        Binding("escape", "back", "Back", show=True),
        Binding("c", "request_cancel", "Cancel", show=True),
        Binding("v", "details", "Details", show=True),
        Binding("h", "history", "History", show=True),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._timer: Timer | None = None
        self._rows: dict[str, Vertical] = {}
        self._rendered: tuple | None = None
        self._history_rendered: tuple | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with ScrollableContainer(id="main-panel"):
            yield Label("Downloads", id="dl-title", markup=False)
            yield Label("", id="progress-context", markup=False)
            with Vertical(id="progress-overall"):
                yield Label("", id="progress-overall-text", markup=False)
                yield ProgressBar(total=1, show_eta=False, id="progress-overall-bar")
            yield Label("", id="summary-line", markup=False)
            yield Static("Active", classes="dl-section-title")
            yield Label("", id="progress-empty", markup=False)
            yield Vertical(id="progress-active")
            yield Static("Recent results", classes="dl-section-title")
            yield Vertical(id="progress-completed")
            with Collapsible(
                title="Verification and provider details",
                collapsed=True,
                id="progress-details",
            ):
                yield Label("", id="progress-detail-text", markup=False)
        yield Footer()

    async def on_mount(self) -> None:
        self._rendered = None
        self._history_rendered = None
        await self._refresh_session()
        self._timer = self.set_interval(0.25, self._refresh_session)

    def on_unmount(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
        self._rows.clear()

    async def _refresh_session(self) -> None:
        session: DownloadSession | None = self.app.download_session  # pyright: ignore[reportAttributeAccessIssue]
        if session is None:
            self.query_one("#progress-context", Label).update(
                "No download session. Go back and choose games to begin."
            )
            self.query_one("#progress-empty", Label).update("No downloads started.")
            self.query_one("#progress-overall", Vertical).display = False
            return
        if self.app.screen is self and not session.running:
            session.unread = False
        snapshot = (
            id(session),
            session.revision,
            self.size.width,
            session.running,
            session.cancelling,
        )
        if snapshot == self._rendered:
            return
        self._rendered = snapshot
        self.query_one("#progress-overall", Vertical).display = True
        mode = "Dry run" if session.dry_run else "Downloads"
        self.query_one("#dl-title", Label).update(f"{mode}: {session.shortname}")
        context = "Esc goes back. Downloads continue in this app; F6 reopens this view."
        if session.dry_run:
            context = "Preview only. No files are downloaded. Esc goes back; F6 reopens this view."
        elif not session.running:
            context = "Session finished. Esc goes back; h opens download history."
        self.query_one("#progress-context", Label).update(context)
        self.query_one("#progress-overall-text", Label).update(
            f"{session.processed_count} / {len(session.wantlist)} processed"
        )
        self.query_one("#progress-overall-bar", ProgressBar).update(
            total=max(1, len(session.wantlist)), progress=session.progress
        )
        summary = self.query_one("#summary-line", Label)
        summary.update(f"Failed: {session.error}" if session.error else session.summary)
        summary.set_class(bool(session.error), "status-failed")
        empty = self.query_one("#progress-empty", Label)
        empty.display = not session.active
        empty.update(
            "Stopping downloads; waiting for cleanup."
            if session.cancelling and session.running
            else "Preparing downloads; waiting for the next transfer."
            if session.running
            else "No active downloads. Session finished."
        )
        active = self.query_one("#progress-active", Vertical)
        for key in self._rows.keys() - session.active.keys():
            await self._rows.pop(key).remove()
        for key, item in session.active.items():
            row = self._rows.get(key)
            if row is None:
                row = Vertical(
                    Label("", classes="dl-active-title", markup=False),
                    Label("", classes="dl-active-metrics", markup=False),
                    classes="dl-active-row",
                )
                await active.mount(row)
                self._rows[key] = row
            row.query_one(".dl-active-title", Label).update(item.title)
            phase = item.stage.replace("_", " ").capitalize()
            if item.source:
                phase += f" via {item.source}"
            size = f"{format_bytes(item.downloaded)} / "
            if item.total > 0:
                percent = min(100, max(0, item.downloaded * 100 / item.total))
                size += f"{format_bytes(item.total)} ({percent:.0f}%)"
            else:
                size += "size unknown"
            metrics = f"{phase}  {size}  {format_speed(item.speed_bps)}"
            if item.eta_seconds is not None:
                metrics += f"  ETA {format_eta(item.eta_seconds)}"
            if item.seeds is not None and item.peers is not None:
                peers = f"  {item.seeds} seeds / {item.peers} peers"
                if len(metrics + peers) <= max(0, self.size.width - 8):
                    metrics += peers
            row.query_one(".dl-active-metrics", Label).update(metrics)
        history_snapshot = (id(session), session.history_revision)
        if history_snapshot != self._history_rendered:
            self._history_rendered = history_snapshot
            self.app.refresh_bindings()
            recent = self.query_one("#progress-completed", Vertical)
            await recent.remove_children()
            for record in reversed(session.recent):
                text = f"{record.outcome.upper()}: {record.title}"
                if record.outcome == "failed" and record.detail:
                    text += f"\n{record.detail}"
                status = (
                    "failed"
                    if record.outcome == "failed"
                    else "acquired"
                    if record.outcome == "downloaded"
                    else "pending"
                )
                await recent.mount(
                    Label(text, classes=f"dl-status-row status-{status}", markup=False)
                )
        details = [session.verification_detail] if session.verification_detail else []
        details.extend(session.notices)
        details.extend(
            f"{item.title}: {item.detail}"
            for item in session.active.values()
            if item.detail
        )
        for record in reversed(session.recent):
            metadata = "; ".join(
                value
                for value in (record.source, record.verification, record.detail)
                if value
            )
            if metadata:
                details.append(f"{record.title}: {metadata}")
        self.query_one("#progress-detail-text", Label).update(
            "\n".join(details) or "No additional details yet."
        )

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == "request_cancel":
            session = self.app.download_session  # pyright: ignore[reportAttributeAccessIssue]
            return session is not None and session.running and not session.cancelling
        return True

    def action_back(self) -> None:
        self.dismiss(None)

    def action_request_cancel(self) -> None:
        session = self.app.download_session  # pyright: ignore[reportAttributeAccessIssue]
        if session is not None and session.running and not session.cancelling:
            self.app.push_screen(CancelConfirmScreen(), self._on_cancel_decision)

    def _on_cancel_decision(self, confirmed: bool | None) -> None:
        if confirmed:
            self.app.cancel_download()  # pyright: ignore[reportAttributeAccessIssue]
            self.app.refresh_bindings()

    def action_details(self) -> None:
        details = self.query_one("#progress-details", Collapsible)
        details.collapsed = not details.collapsed

    def action_history(self) -> None:
        session = self.app.download_session  # pyright: ignore[reportAttributeAccessIssue]
        if session is not None:
            self.app.push_screen(StateScreen(console_entry=session.console_entry))
