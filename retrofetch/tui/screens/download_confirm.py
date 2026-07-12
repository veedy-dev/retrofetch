"""Download confirm screen: validates selected wantlist, then pushes Progress."""
from __future__ import annotations

from typing import Any

from textual import work  # pyright: ignore[reportMissingImports, reportAttributeAccessIssue]
from textual.app import ComposeResult  # pyright: ignore[reportMissingImports]
from textual.binding import Binding  # pyright: ignore[reportMissingImports]
from textual.containers import Vertical  # pyright: ignore[reportMissingImports]
from textual.screen import Screen  # pyright: ignore[reportMissingImports]
from textual.widgets import Footer, Header, Label, OptionList  # pyright: ignore[reportMissingImports]

from retrofetch.config import ConsoleOverride
from retrofetch.ranker import resolve_download_set
from retrofetch.tui.screens.download_progress import DownloadProgressScreen
from retrofetch.tui.messages import WantlistFailed, WantlistReady
from retrofetch.wantlist_cache import get_or_fetch_wantlist


class DownloadConfirmScreen(Screen[None]):
    BINDINGS = [
        Binding("enter", "start", "Start", show=True, priority=True),
        Binding("x", "remove", "Remove", show=True),
        Binding("delete", "remove", "Remove", show=False),
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
        self._wantlist: list[str] = []
        self._loaded: bool = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Vertical(id="main-panel"):
            yield Label(
                f"Download: {self.shortname}. Enter=start, x/delete=remove, c=cancel, esc=back.",
                id="dl-title",
            )
            yield Label("", id="summary-line")
            yield OptionList(id="wantlist-preview", markup=False)
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#summary-line", Label).update("Loading games...")
        self._kick_load()

    @work(thread=True, exclusive=True, group="confirm-load")
    def _kick_load(self) -> None:
        try:
            titles, from_cache = get_or_fetch_wantlist(
                console_entry=self.console_entry,
                overrides=self.override,
                config=self.app.config,  # pyright: ignore[reportAttributeAccessIssue]
                limit=0,
            )
        except Exception as exc:
            self.post_message(WantlistFailed(self.shortname, str(exc)))
            return
        self.post_message(WantlistReady(self.shortname, titles, from_cache))

    def _has_selection(self) -> bool:
        return self.override is not None and bool(self.override.include)

    def on_wantlist_ready(self, message: WantlistReady) -> None:
        if message.console != self.shortname:
            return
        limit = (
            self.override.limit
            if (self.override and self.override.limit)
            else self.app.config.default_limit  # pyright: ignore[reportAttributeAccessIssue]
        )
        self._wantlist = resolve_download_set(
            list(message.titles),
            self.override,
            limit,
        )
        self._loaded = True
        if not self._has_selection():
            self.query_one("#summary-line", Label).update(
                "No games selected. Press Esc, then press g to select games."
            )
            return
        indicator = "cached" if message.from_cache else "fresh"
        self.query_one("#summary-line", Label).update(
            f"Queued {len(self._wantlist)} selected games ({indicator}); source availability is checked at start. Use arrows and x/delete to remove."
        )
        preview = self.query_one("#wantlist-preview", OptionList)
        for title in self._wantlist:
            display = title if len(title) <= 80 else title[:77] + "..."
            preview.add_option(f"- {display}")
        preview.highlighted = 0
        preview.focus()

    def on_wantlist_failed(self, message: WantlistFailed) -> None:
        if message.console != self.shortname:
            return
        self._wantlist = []
        self._loaded = False
        self.query_one("#summary-line", Label).update(
            f"Failed to load games: {message.reason}"
        )

    def action_start(self) -> None:
        if not self._has_selection():
            self.query_one("#summary-line", Label).update(
                "No games selected. Press Esc, then press g to select games."
            )
            return
        if not self._loaded or not self._wantlist:
            self.query_one("#summary-line", Label).update(
                "Download list is empty or not ready. Press Esc to choose games."
            )
            return
        self.app.config.dry_run = False  # pyright: ignore[reportAttributeAccessIssue]
        self.app.switch_screen(
            DownloadProgressScreen(
                console_entry=self.console_entry,
                wantlist=self._wantlist,
                dry_run=False,
            )
        )

    def action_remove(self) -> None:
        if not self._loaded or not self._wantlist:
            return
        preview = self.query_one("#wantlist-preview", OptionList)
        index = preview.highlighted
        if index is None:
            return
        title = self._wantlist.pop(index)
        preview.remove_option_at_index(index)
        if self._wantlist:
            noun = "game" if len(self._wantlist) == 1 else "games"
            self.query_one("#summary-line", Label).update(
                f'Removed "{title}" from this download. {len(self._wantlist)} {noun} remain.'
            )
        else:
            self.query_one("#summary-line", Label).update(
                "Download list is empty. Press Esc to choose games."
            )

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_back(self) -> None:
        self.dismiss(None)
