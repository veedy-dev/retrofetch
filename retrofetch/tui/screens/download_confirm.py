"""Review the shared pending queue and start an app-owned download batch."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from rich.text import Text
from textual.app import ComposeResult  # pyright: ignore[reportMissingImports]
from textual.binding import Binding  # pyright: ignore[reportMissingImports]
from textual.containers import Vertical  # pyright: ignore[reportMissingImports]
from textual.screen import Screen  # pyright: ignore[reportMissingImports]
from textual.widgets import (  # pyright: ignore[reportMissingImports]
    Footer,
    Header,
    Label,
    OptionList,
)

from retrofetch.config import ConsoleOverride
from retrofetch.ranker import resolve_download_set
from retrofetch.tui.messages import QueueChanged
from retrofetch.tui.screens.download_progress import DownloadProgressScreen

if TYPE_CHECKING:
    from retrofetch.tui.app import RetrofetchApp


class DownloadConfirmScreen(Screen[None]):
    BINDINGS = [
        Binding("enter", "start", "Start", show=True, priority=True),
        Binding("x", "remove", "Remove", show=True),
        Binding("delete", "remove", "Remove", show=False),
        Binding("g", "choose_games", "Choose games", show=True),
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
        self._wantlist: list[str] = []
        self._loaded: bool = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Vertical(id="main-panel"):
            yield Label(
                f"Pending queue: {self.shortname}",
                id="dl-title",
                markup=False,
            )
            yield Label("", id="summary-line")
            yield OptionList(id="wantlist-preview", markup=False)
        yield Footer()

    def on_mount(self) -> None:
        self._refresh_queue()
        self.query_one("#wantlist-preview", OptionList).focus()

    def _refresh_queue(self) -> None:
        self.override = cast("RetrofetchApp", self.app).overrides.get(self.shortname)
        override = self.override
        self._wantlist = (
            resolve_download_set(list(override.include), override, 0)
            if override and override.include
            else []
        )
        self._loaded = True
        preview = self.query_one("#wantlist-preview", OptionList)
        index = preview.highlighted or 0
        preview.clear_options()
        preview.add_options([Text(title) for title in self._wantlist])
        if self._wantlist:
            preview.highlighted = min(index, len(self._wantlist) - 1)
        summary = (
            f"{len(self._wantlist)} queued. Enter starts; x removes. Source availability is checked at start."
            if self._wantlist
            else "Your queue is empty. Press g to choose games."
        )
        self.query_one("#summary-line", Label).update(Text(summary))

    def on_queue_changed(self, message: QueueChanged) -> None:
        if message.console == self.shortname:
            self._refresh_queue()

    def on_screen_resume(self) -> None:
        if self._loaded:
            self._refresh_queue()

    def action_start(self) -> None:
        app = cast("RetrofetchApp", self.app)
        self._refresh_queue()
        if not self._wantlist:
            return
        if app.start_download(self.console_entry, list(self._wantlist), dry_run=False):
            app.switch_screen(DownloadProgressScreen())
        else:
            app.show_toast(
                "A download batch is still running. Your selections are saved; showing its progress."
            )
            app.action_downloads()

    def action_remove(self) -> None:
        app = cast("RetrofetchApp", self.app)
        preview = self.query_one("#wantlist-preview", OptionList)
        index = preview.highlighted
        if index is None or index >= len(self._wantlist):
            return
        title = self._wantlist[index]
        override = app.overrides.get(self.shortname)
        if override is not None:
            app.update_selection(
                self.shortname,
                [name for name in override.include if name != title],
                list(override.exclude),
            )
        self._refresh_queue()

    def action_choose_games(self) -> None:
        from retrofetch.tui.screens.wantlist import WantlistScreen

        app = cast("RetrofetchApp", self.app)
        app.push_screen(
            WantlistScreen(
                console_entry=self.console_entry,
                override=app.overrides.get(self.shortname),
            )
        )

    def action_back(self) -> None:
        self.dismiss(None)
