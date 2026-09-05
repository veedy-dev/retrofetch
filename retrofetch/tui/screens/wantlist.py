"""Browse a complete catalog and edit the shared session-only queue."""

from __future__ import annotations

# pyright: reportAttributeAccessIssue=false
from typing import Any

from rich.text import Text
from textual import (
    work,  # pyright: ignore[reportMissingImports, reportAttributeAccessIssue]
)
from textual.app import ComposeResult  # pyright: ignore[reportMissingImports]
from textual.binding import Binding  # pyright: ignore[reportMissingImports]
from textual.containers import Vertical  # pyright: ignore[reportMissingImports]
from textual.coordinate import Coordinate
from textual.screen import Screen  # pyright: ignore[reportMissingImports]
from textual.widgets import (  # pyright: ignore[reportMissingImports]
    DataTable,
    Footer,
    Header,
    Input,
    Label,
)

from retrofetch.config import ConsoleOverride
from retrofetch.tui.messages import QueueChanged, WantlistFailed, WantlistReady
from retrofetch.wantlist_cache import get_or_fetch_wantlist

_SPINNER_FRAMES = ("|", "/", "-", "\\")
_SPINNER_INTERVAL_S = 0.12


class WantlistScreen(Screen[None]):
    BINDINGS = [
        Binding("escape", "cancel", "Back", show=True, priority=True),
        Binding("space", "toggle_include", "Queue", show=True),
        Binding("enter", "enter", "Review queue", show=True, priority=True),
        Binding("slash", "focus_filter", "Search", show=True, key_display="/"),
        Binding("s", "queued_only", "Queued only", show=True),
        Binding("x", "toggle_exclude", "Exclude", show=True),
        Binding("ctrl+a", "select_filtered", "Queue results", show=True),
        Binding("ctrl+u", "clear_filtered", "Clear results", show=True),
        Binding("r", "refresh", "Refresh", show=True),
        Binding("pageup", "page_prev", "Prev page", show=True),
        Binding("pagedown", "page_next", "Next page", show=True),
    ]

    _PAGE_SIZE = 100

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
        # Refresh from the shared session selection before every mutation.
        self._include: set[str] = set(self.override.include)
        self._exclude: set[str] = set(self.override.exclude)
        self._wantlist: list[str] = []
        self._filtered_wantlist: list[str] = []
        self._filter_query = ""
        self._page = 0
        self._status = ""
        self._queued_only = False
        self._loaded = False
        self._loading = False
        self._spinner_timer = None
        self._spinner_index: int = 0
        self._session_status_key: tuple[int, int] | None = None
        self._table_width = 0

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Vertical(id="main-panel"):
            yield Label(
                f"Browse games: {self.shortname}", id="browser-title", markup=False
            )
            yield Label(
                "Space queues a game. Selections stay for this session; Esc goes back.",
                id="browser-context",
            )
            yield Input(placeholder="search titles...", id="wantlist-filter")
            yield Label("", id="status-line")
            yield DataTable(id="wantlist-table")
            yield Label("", id="game-detail", markup=False)
        yield Footer()

    def on_mount(self) -> None:
        table: DataTable = self.query_one("#wantlist-table", DataTable)
        self._set_columns(table)
        table.cursor_type = "row"
        table.focus()
        self._sync_selection()
        self._begin_load()
        self.set_interval(0.25, self._refresh_download_status)

    def _refresh_download_status(self) -> None:
        if not self._loaded or not self.is_current:
            return
        session = self.app.download_session
        key = (id(session), session.status_revision if session is not None else 0)
        if key == self._session_status_key:
            return
        self._session_status_key = key
        table = self.query_one("#wantlist-table", DataTable)
        start = self._page * self._PAGE_SIZE
        for row, title in enumerate(
            self._filtered_wantlist[start : start + self._PAGE_SIZE]
        ):
            table.update_cell_at(
                Coordinate(row, 2), self._cell_text(self._title_status(title), 16)
            )

    @staticmethod
    def _cell_text(value: str, width: int) -> Text:
        text = Text(value)
        if text.cell_len > width:
            text.truncate(max(0, width - 3), overflow="crop")
            text.append("...")
        return text

    def _set_columns(self, table: DataTable) -> int:
        self._table_width = table.content_size.width
        # Reserve all cell padding and the scrollbar before assigning title space.
        title_width = max(
            5, self._table_width - table.styles.scrollbar_size_vertical - 27
        )
        table.add_column("Queue", width=5)
        table.add_column("Title", width=title_width)
        table.add_column("Status", width=16)
        return title_width

    def on_resize(self) -> None:
        if self._loaded:
            self.call_after_refresh(self._resize_table)

    def _resize_table(self) -> None:
        if (
            self.query_one("#wantlist-table", DataTable).content_size.width
            != self._table_width
        ):
            self._render_page()

    def on_data_table_row_highlighted(self) -> None:
        self._update_game_detail()

    def _update_game_detail(self) -> None:
        self.query_one("#game-detail", Label).update(Text(self._current_title() or ""))

    def _begin_load(self) -> None:
        if self._loading:
            return
        self._loading = True
        self._loaded = False
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
        self._loading = False
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
        self._loading = False
        self._wantlist = []
        self._filtered_wantlist = []
        self._loaded = True
        self._stop_loading_spinner()
        self._set_status(f"error: {message.reason}")
        self._render_page()

    def _render_page(self) -> None:
        table = self.query_one("#wantlist-table", DataTable)
        row = table.cursor_row
        self._sync_selection()
        self._apply_title_filter(reset_page=False)
        table.clear(columns=True)
        title_width = self._set_columns(table)
        start = self._page * self._PAGE_SIZE
        for title in self._filtered_wantlist[start : start + self._PAGE_SIZE]:
            table.add_row(
                Text("[x]" if title in self._include else "[ ]"),
                self._cell_text(title, title_width),
                self._cell_text(self._title_status(title), 16),
            )
        if table.row_count:
            table.move_cursor(row=min(row, table.row_count - 1))
        self._refresh_status_line()
        self._update_game_detail()

    def _title_status(self, title: str) -> str:
        status = "Excluded" if title in self._exclude else ""
        session = self.app.download_session
        if session is not None and session.shortname == self.shortname:
            activity = session.title_status.get(title, "")
            if activity:
                status = activity
        return status

    def _sync_selection(self) -> None:
        self.override = self.app.overrides.get(self.shortname) or ConsoleOverride()
        self._include = set(self.override.include)
        self._exclude = set(self.override.exclude)

    def _save_selection(self) -> None:
        self.app.update_selection(
            self.shortname, sorted(self._include), sorted(self._exclude)
        )
        self._render_page()

    def on_queue_changed(self, message: QueueChanged) -> None:
        if message.console == self.shortname and self._loaded:
            self._render_page()

    def on_screen_resume(self) -> None:
        if self._loaded:
            self._render_page()

    def _refresh_status_line(self) -> None:
        total = len(self._filtered_wantlist)
        raw_total = len(self._wantlist)
        total_pages = max(1, (total + self._PAGE_SIZE - 1) // self._PAGE_SIZE)
        if total == 0 and self._status.startswith("error:"):
            return
        search_note = (
            f" matched from {raw_total}"
            if self._filter_query and raw_total != total
            else ""
        )
        status = (
            f"{total} {'queued matches' if self._queued_only else 'titles'}{search_note}  |  "
            f"page {self._page + 1}/{total_pages}  |  "
            f"queued: {len(self._include)}  excluded: {len(self._exclude)}"
        )
        self._set_status(status)

    def _set_status(self, msg: str) -> None:
        self._status = msg
        try:
            self.query_one("#status-line", Label).update(Text(msg))
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
        self._filtered_wantlist = [
            title
            for title in self._wantlist
            if (not query or query in title.casefold())
            and (not self._queued_only or title in self._include)
        ]
        if reset_page:
            self._page = 0
        self._page = min(
            self._page, max(0, (len(self._filtered_wantlist) - 1) // self._PAGE_SIZE)
        )

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
        self._sync_selection()
        if title in self._include:
            self._include.discard(title)
        else:
            self._include.add(title)
            self._exclude.discard(title)
        self._save_selection()

    def action_toggle_exclude(self) -> None:
        title = self._current_title()
        if title is None:
            return
        self._sync_selection()
        if title in self._exclude:
            self._exclude.discard(title)
        else:
            self._exclude.add(title)
            self._include.discard(title)
        self._save_selection()

    def action_queued_only(self) -> None:
        self._queued_only = not self._queued_only
        self._page = 0
        self._render_page()

    def action_select_filtered(self) -> None:
        self._sync_selection()
        self._apply_title_filter(reset_page=False)
        self._include.update(self._filtered_wantlist)
        self._exclude.difference_update(self._filtered_wantlist)
        self._save_selection()

    def action_clear_filtered(self) -> None:
        self._sync_selection()
        self._apply_title_filter(reset_page=False)
        self._include.difference_update(self._filtered_wantlist)
        self._save_selection()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        return not (
            isinstance(self.focused, Input)
            and action not in {"enter", "cancel", "focus_filter"}
        )

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
        if self._loading:
            return
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
        self._begin_load()

    def action_cancel(self) -> None:
        if isinstance(self.focused, Input):
            self.query_one("#wantlist-table", DataTable).focus()
        else:
            self.dismiss(None)

    def action_enter(self) -> None:
        if isinstance(self.focused, Input):
            self.query_one("#wantlist-table", DataTable).focus()
            return
        from retrofetch.tui.screens.download_confirm import DownloadConfirmScreen

        self.app.push_screen(
            DownloadConfirmScreen(
                console_entry=self.console_entry,
                override=self.app.overrides.get(self.shortname),
            )
        )
