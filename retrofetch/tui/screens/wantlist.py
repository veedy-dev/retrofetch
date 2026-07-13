"""Wantlist curation screen - session-only DataTable multi-select.

Pushed from HomeScreen when the user presses 'w' on a selected Class A/B/C console.
Displays ranked titles with include/exclude state, paginated to keep the table
responsive for large catalogs.

Selections update the running TUI only. Reopening Retrofetch starts with a clean
wantlist while download progress/history remains persisted separately.
"""

from __future__ import annotations

# pyright: reportAttributeAccessIssue=false

from typing import Any

from rich.text import Text
from textual import work  # pyright: ignore[reportMissingImports, reportAttributeAccessIssue]
from textual.app import ComposeResult  # pyright: ignore[reportMissingImports]
from textual.binding import Binding  # pyright: ignore[reportMissingImports]
from textual.containers import Vertical  # pyright: ignore[reportMissingImports]
from textual.coordinate import Coordinate  # pyright: ignore[reportMissingImports]
from textual.screen import Screen  # pyright: ignore[reportMissingImports]
from textual.widgets import DataTable, Footer, Header, Input, Label  # pyright: ignore[reportMissingImports]

from retrofetch.config import ConsoleOverride
from retrofetch.tui.messages import WantlistFailed, WantlistReady
from retrofetch.wantlist_cache import get_or_fetch_wantlist


_SPINNER_FRAMES = ("|", "/", "-", "\\")
_SPINNER_INTERVAL_S = 0.12


class WantlistScreen(Screen[None]):
    BINDINGS = [
        Binding("space", "toggle_include", "Include", show=True),
        Binding("x", "toggle_exclude", "Exclude", show=True),
        Binding("enter", "enter", "Apply", show=True, priority=True),
        Binding("slash", "focus_filter", "Search", show=True, key_display="/"),
        Binding("r", "refresh", "Refresh", show=True),
        Binding("escape", "cancel", "Cancel", show=True),
        Binding("pageup", "page_prev", "Prev page", show=True),
        Binding("pagedown", "page_next", "Next page", show=True),
    ]

    _PAGE_SIZE = 500

    def __init__(
        self,
        *,
        console_entry: dict[str, Any],
        override: ConsoleOverride | None,
    ) -> None:
        super().__init__()
        self.console_entry = console_entry
        self.shortname = str(console_entry.get("shortname", "?"))
        self.override = override or ConsoleOverride()
        # Working copies so esc can discard unsaved changes
        self._include: set[str] = set(self.override.include)
        self._exclude: set[str] = set(self.override.exclude)
        self._wantlist: list[str] = []
        self._filtered_wantlist: list[str] = []
        self._filter_query = ""
        self._page = 0
        self._status = ""
        self._primary_source: str = "-"
        self._loaded = False
        self._spinner_timer = None
        self._spinner_index: int = 0

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Vertical(id="main-panel"):
            yield Label(
                f"Select Games: {self.shortname}  (space=include, x=exclude, /=search, enter=apply, r=refresh, esc=cancel)"
            )
            yield Input(placeholder="search titles...", id="wantlist-filter")
            yield Label("", id="status-line")
            yield DataTable(id="wantlist-table")
        yield Footer()

    def on_mount(self) -> None:
        table: DataTable = self.query_one("#wantlist-table", DataTable)
        table.add_columns("#", "sel", "Title", "Source", "Included", "Excluded")
        table.cursor_type = "row"
        table.focus()
        klass = str(self.console_entry.get("class", "?"))
        ranking_sources = self.app.config.ranking_sources_by_class.get(klass, [])  # pyright: ignore[reportAttributeAccessIssue]
        self._primary_source = ranking_sources[0] if ranking_sources else "-"
        # Kick background loader. UI remains responsive; handler fills the table.
        self._start_loading_spinner()
        self._kick_load()

    def _start_loading_spinner(self) -> None:
        self._spinner_index = 0
        self._update_loading_status_line()
        if self._spinner_timer is None:
            try:
                self._spinner_timer = self.set_interval(
                    _SPINNER_INTERVAL_S, self._tick_spinner
                )
            except Exception:
                self._spinner_timer = None

    def _stop_loading_spinner(self) -> None:
        if self._spinner_timer is not None:
            try:
                self._spinner_timer.stop()
            except Exception:
                pass
            self._spinner_timer = None

    def _tick_spinner(self) -> None:
        # Stop ticking once the load finishes (either way, the status line
        # gets overwritten by _refresh_status_line on WantlistReady or
        # _set_status on WantlistFailed).
        if self._loaded:
            self._stop_loading_spinner()
            return
        self._spinner_index = (self._spinner_index + 1) % len(_SPINNER_FRAMES)
        self._update_loading_status_line()

    def _update_loading_status_line(self) -> None:
        frame = _SPINNER_FRAMES[self._spinner_index]
        self._set_status(f"Loading games for {self.shortname}...  {frame}")

    @work(thread=True, exclusive=True, group="wantlist-load")
    def _kick_load(self) -> None:
        try:
            titles, from_cache = get_or_fetch_wantlist(
                console_entry=self.console_entry,
                overrides=None,  # raw ranking; UI applies user's include/exclude
                config=self.app.config,  # pyright: ignore[reportAttributeAccessIssue]
                limit=0,
            )
        except Exception as exc:
            self.post_message(WantlistFailed(self.shortname, str(exc)))
            return
        self.post_message(WantlistReady(self.shortname, titles, from_cache))

    def on_wantlist_ready(self, message: WantlistReady) -> None:
        if message.console != self.shortname:
            return
        self._wantlist = list(message.titles)
        self._apply_title_filter(reset_page=True)
        self._loaded = True
        self._status = ""
        self._page = 0
        self._stop_loading_spinner()
        self._render_page()

    def on_wantlist_failed(self, message: WantlistFailed) -> None:
        if message.console != self.shortname:
            return
        self._wantlist = []
        self._filtered_wantlist = []
        self._loaded = True
        self._stop_loading_spinner()
        self._set_status(f"error: {message.reason}")
        self._render_page()

    def _render_page(self) -> None:
        table: DataTable = self.query_one("#wantlist-table", DataTable)
        table.clear()
        start = self._page * self._PAGE_SIZE
        end = start + self._PAGE_SIZE
        page_rows = self._filtered_wantlist[start:end]
        for offset, title in enumerate(page_rows):
            inc = Text("[x]" if title in self._include else "[ ]")
            table.add_row(
                str(start + offset + 1),
                inc,
                title,
                self._primary_source,
                "yes" if title in self._include else "",
                "yes" if title in self._exclude else "",
            )
        # Reset the viewport to the top on each page render so rows are never
        # stranded mid-scroll.
        try:
            if page_rows:
                table.cursor_coordinate = Coordinate(0, 0)
                table.scroll_home(animate=False)
        except Exception:
            # Textual API variant: scroll_home might differ
            pass
        self._refresh_status_line()

    def _update_current_row_cells(self, title: str) -> None:
        table: DataTable = self.query_one("#wantlist-table", DataTable)
        row = table.cursor_row
        inc_text = Text("[x]" if title in self._include else "[ ]")
        included = "yes" if title in self._include else ""
        excluded = "yes" if title in self._exclude else ""
        try:
            table.update_cell_at(Coordinate(row, 1), inc_text)
            table.update_cell_at(Coordinate(row, 4), included)
            table.update_cell_at(Coordinate(row, 5), excluded)
        except Exception:
            self._render_page()
            return
        self._refresh_status_line()

    def _refresh_status_line(self) -> None:
        total = len(self._filtered_wantlist)
        raw_total = len(self._wantlist)
        total_pages = max(1, (total + self._PAGE_SIZE - 1) // self._PAGE_SIZE)
        if total == 0 and self._status:
            # Preserve an error/failure status when the list is empty
            return
        search_note = (
            f" matched from {raw_total}"
            if self._filter_query and raw_total != total
            else ""
        )
        status = (
            f"{total} titles{search_note}  |  "
            f"page {self._page + 1}/{total_pages}  |  "
            f"included: {len(self._include)}  excluded: {len(self._exclude)}"
        )
        self._set_status(status)

    def _set_status(self, msg: str) -> None:
        self._status = msg
        try:
            self.query_one("#status-line", Label).update(msg)
        except Exception:
            # defensive: status Label may be unmounted during teardown
            pass

    def _current_title(self) -> str | None:
        table: DataTable = self.query_one("#wantlist-table", DataTable)
        row = table.cursor_row
        start = self._page * self._PAGE_SIZE
        idx = start + row
        if 0 <= idx < len(self._filtered_wantlist):
            return self._filtered_wantlist[idx]
        return None

    def _apply_title_filter(self, *, reset_page: bool) -> None:
        query = self._filter_query.casefold().strip()
        if not query:
            self._filtered_wantlist = list(self._wantlist)
        else:
            self._filtered_wantlist = [
                title for title in self._wantlist if query in title.casefold()
            ]
        if reset_page:
            self._page = 0

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "wantlist-filter":
            return
        self._filter_query = event.value
        self._apply_title_filter(reset_page=True)
        if self._loaded:
            self._render_page()

    def action_focus_filter(self) -> None:
        self.query_one("#wantlist-filter", Input).focus()

    def action_toggle_include(self) -> None:
        title = self._current_title()
        if title is None:
            return
        if title in self._include:
            self._include.discard(title)
        else:
            self._include.add(title)
            self._exclude.discard(title)
        self._update_current_row_cells(title)

    def action_toggle_exclude(self) -> None:
        title = self._current_title()
        if title is None:
            return
        if title in self._exclude:
            self._exclude.discard(title)
        else:
            self._exclude.add(title)
            self._include.discard(title)
        self._update_current_row_cells(title)

    def action_page_prev(self) -> None:
        if self._page > 0:
            self._page -= 1
            self._render_page()

    def action_page_next(self) -> None:
        total_pages = max(
            1, (len(self._filtered_wantlist) + self._PAGE_SIZE - 1) // self._PAGE_SIZE
        )
        if self._page < total_pages - 1:
            self._page += 1
            self._render_page()

    def action_refresh(self) -> None:
        """Force a fresh fetch: invalidate cache + re-kick the worker."""
        from retrofetch.wantlist_cache import invalidate

        try:
            cache_dir = self.app.config.cache_dir  # pyright: ignore[reportAttributeAccessIssue]
            invalidate(cache_dir, self.shortname)
        except Exception:
            pass
        self._wantlist = []
        self._filtered_wantlist = []
        self._loaded = False
        self._page = 0
        self._render_page()
        self._start_loading_spinner()
        self._kick_load()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_enter(self) -> None:
        self.override = self.override.model_copy(
            update={"include": sorted(self._include), "exclude": sorted(self._exclude)}
        )
        self.app.overrides[self.shortname] = self.override
        self.dismiss(None)
