"""Read-only, asynchronously loaded download history for a console."""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Label
from textual.worker import get_current_worker

from retrofetch.state import GameEntry, State, load_state, state_path
from retrofetch.tui.downloads import format_bytes


class StateScreen(Screen[None]):
    BINDINGS: ClassVar[list[Binding]] = [
        Binding("r", "refresh", "Refresh", show=True),
        Binding("escape", "back", "Back", show=True),
    ]

    def __init__(self, *, console_entry: dict[str, Any]) -> None:
        super().__init__()
        self.console_entry = console_entry
        self.shortname = str(console_entry.get("shortname", "?"))
        self._games: dict[str, GameEntry] = {}
        self._generation = 0
        self._table_width = 0

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Vertical(id="main-panel"):
            yield Label(Text(f"History / {self.shortname}"), id="st-title")
            yield Label("Loading history…", id="st-summary")
            yield DataTable(id="state-table", cursor_type="row")
            with VerticalScroll(id="history-details-pane"):
                yield Label("", id="history-details")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#state-table", DataTable)
        self._render_table()
        table.focus()

    def on_screen_resume(self) -> None:
        if (
            self.query("#state-table")
            and self.query_one("#state-table", DataTable).columns
        ):
            self.action_refresh()

    def action_refresh(self) -> None:
        self._generation += 1
        self.query_one("#st-summary", Label).update(
            "Refreshing history…" if self._games else "Loading history…"
        )
        root = self.app.config.roms_root  # pyright: ignore[reportAttributeAccessIssue]
        self._load_history(Path(root), self._generation)

    @work(thread=True, exclusive=True)
    def _load_history(self, root: Path, generation: int) -> None:
        worker = get_current_worker()
        try:
            path = state_path(self.shortname, root)
            existed = path.exists()
            state = load_state(self.shortname, root)
            recovered = existed and not path.exists()
        except (OSError, ValueError, TypeError, KeyError) as exc:
            if not worker.is_cancelled:
                self.app.call_from_thread(self._show_failure, generation, str(exc))
        else:
            if not worker.is_cancelled:
                self.app.call_from_thread(
                    self._show_history, generation, state, recovered
                )

    def _show_failure(self, generation: int, error: str) -> None:
        if not self.is_mounted or generation != self._generation:
            return
        retained = " Showing the previous snapshot." if self._games else ""
        self.query_one("#st-summary", Label).update(
            Text(
                f"Could not load history: {error}.{retained} Press r to retry or Esc to go back."
            )
        )
        if not self._games:
            self.query_one("#history-details", Label).update(
                "History is unavailable. Your downloads have not been changed."
            )

    @staticmethod
    def _result(game: GameEntry) -> str:
        status = game.outcome or game.status
        return {
            "acquired": "Downloaded",
            "unverified": "Downloaded",
            "failed": "Failed",
            "cancelled": "Cancelled",
            "skipped": "Skipped",
            "pending": "In progress",
        }.get(status, status.capitalize())

    @staticmethod
    def _cell_text(value: str, width: int) -> Text:
        text = Text(value)
        if text.cell_len > width:
            text.truncate(max(0, width - 3), overflow="crop")
            text.append("...")
        return text

    def on_resize(self) -> None:
        if self.is_mounted:
            self.call_after_refresh(self._resize_table)

    def _resize_table(self) -> None:
        if (
            self.query_one("#state-table", DataTable).content_size.width
            != self._table_width
        ):
            self._render_table()

    def _render_table(self, selected: str | None = None) -> None:
        table = self.query_one("#state-table", DataTable)
        if selected is None and table.row_count:
            selected = table.coordinate_to_cell_key(
                table.cursor_coordinate
            ).row_key.value
        table.clear(columns=True)
        self._table_width = table.content_size.width
        # Reserve four cells of padding plus the vertical scrollbar.
        title_width = max(5, self._table_width - table.scrollbar_size_vertical - 42)
        for label, width in (
            ("Game", title_width),
            ("Result", 11),
            ("Size", 8),
            ("Provider", 15),
        ):
            table.add_column(label, width=width)
        selected_row = 0
        for index, (key, game) in enumerate(self._games.items()):
            size = (
                game.size_bytes if game.size_bytes is not None else game.selected_bytes
            )
            table.add_row(
                self._cell_text(game.title, title_width),
                Text(self._result(game)),
                self._cell_text(format_bytes(size) if size is not None else "—", 8),
                self._cell_text(game.provider or game.source or "—", 15),
                key=key,
            )
            if key == selected:
                selected_row = index
        if self._games:
            table.move_cursor(row=selected_row)
            self._show_details(list(self._games)[selected_row])
        else:
            self.query_one("#history-details", Label).update("")

    def _show_history(
        self, generation: int, state: State, recovered: bool = False
    ) -> None:
        if not self.is_mounted or generation != self._generation:
            return
        table = self.query_one("#state-table", DataTable)
        selected = (
            table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
            if table.row_count
            else None
        )
        selected_game = self._games.get(selected or "")
        self._games.clear()
        downloaded = attention = pending = skipped = 0
        for index, game in enumerate(state.games):
            key = f"{index}:{game.item_id or ''}"
            self._games[key] = game
            if (
                selected_game is not None
                and game.item_id
                and game.item_id == selected_game.item_id
            ):
                selected = key
            result = self._result(game)
            downloaded += result == "Downloaded"
            attention += result in ("Failed", "Cancelled")
            pending += result == "In progress"
            skipped += result == "Skipped"
        summary = f"Downloaded {downloaded}  /  Needs attention {attention}  /  In progress {pending}"
        if skipped:
            summary += f"  /  Skipped {skipped}"
        self.query_one("#st-summary", Label).update(
            "Unreadable history was preserved in a .corrupt backup beside the state file. Press r to refresh or Esc to go back."
            if recovered
            else summary
            if state.games
            else "No download history for this console yet. Go back to browse games."
        )
        self._render_table(selected)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        self._show_details(event.row_key.value)

    def _show_details(self, key: str | None) -> None:
        game = self._games.get(key or "")
        if game is None:
            return
        verification = {
            "verified": "Verified",
            "unverified": "Not checked",
            "not_applicable": "Not applicable",
        }.get(game.verification or "", "Not checked")
        lines = [
            game.title,
            f"Result: {self._result(game)}  /  Verification: {verification}",
            f"Filename: {game.filename or game.final_path or 'Not recorded'}",
        ]
        lines.append(f"Provider: {game.provider or game.source or 'Not recorded'}")
        if game.item_id:
            lines.append(f"Item ID: {game.item_id}")
        if game.attempts:
            latest = game.attempts[-1]
            lines.append(
                f"Latest attempt ({latest.ts}, {latest.source}): {latest.result}"
            )
            failure = next(
                (
                    attempt
                    for attempt in reversed(game.attempts)
                    if "failed" in attempt.result
                    or attempt.result.startswith("unexpected:")
                ),
                None,
            )
            if failure is not None and failure is not latest:
                lines.append(
                    f"Last failure ({failure.ts}, {failure.source}): {failure.result}"
                )
        if self._result(game) in ("Failed", "Cancelled"):
            lines.append(
                "Retry from the queue, or choose this game in the browser if the queue is empty."
            )
        self.query_one("#history-details", Label).update(Text("\n".join(lines)))

    def action_back(self) -> None:
        self.dismiss(None)
