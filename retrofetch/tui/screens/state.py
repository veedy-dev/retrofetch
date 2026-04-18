"""State browser screen - read-only view of .retrofetch-state.json for a console."""
from __future__ import annotations

from typing import Any

from textual.app import ComposeResult  # pyright: ignore[reportMissingImports]
from textual.binding import Binding  # pyright: ignore[reportMissingImports]
from textual.containers import Vertical  # pyright: ignore[reportMissingImports]
from textual.screen import Screen  # pyright: ignore[reportMissingImports]
from textual.widgets import DataTable, Footer, Header, Label  # pyright: ignore[reportMissingImports]

from retrofetch.state import load_state


class StateScreen(Screen[None]):
    BINDINGS = [
        Binding("r", "refresh", "Refresh", show=True),
        Binding("escape", "back", "Back", show=True),
    ]

    def __init__(self, *, console_entry: dict[str, Any]) -> None:
        super().__init__()
        self.console_entry = console_entry
        self.shortname = str(console_entry.get("shortname", "?"))

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Vertical(id="main-panel"):
            yield Label(f"State: {self.shortname}. r=refresh, esc=back.", id="st-title")
            yield Label("", id="st-summary")
            yield DataTable(id="state-table")
        yield Footer()

    def on_mount(self) -> None:
        table: DataTable = self.query_one("#state-table", DataTable)
        table.add_columns("Title", "Status", "Source", "Size", "SHA1")
        table.cursor_type = "row"
        self.action_refresh()

    def action_refresh(self) -> None:
        roms_root = self.app.config.roms_root  # pyright: ignore[reportAttributeAccessIssue]
        state = load_state(self.shortname, roms_root)
        table: DataTable = self.query_one("#state-table", DataTable)
        table.clear()
        counts: dict[str, int] = {"acquired": 0, "unverified": 0, "failed": 0, "pending": 0}
        for game in state.games:
            table.add_row(
                game.title,
                game.status,
                game.source or "-",
                str(game.size_bytes or "-"),
                (game.sha1[:12] + "...") if game.sha1 else "-",
            )
            counts[game.status] = counts.get(game.status, 0) + 1
        main = self.query_one("#main-panel", Vertical)
        for lbl in list(main.query(".status-cell")):
            lbl.remove()
        for status, count in counts.items():
            if count > 0:
                lbl = Label("", classes=f"status-cell status-{status}")
                lbl.display = False
                main.mount(lbl)
        total = len(state.games)
        self.query_one("#st-summary", Label).update(
            f"{total} games | acquired={counts.get('acquired', 0)} | "
            f"unverified={counts.get('unverified', 0)} | failed={counts.get('failed', 0)} | "
            f"pending={counts.get('pending', 0)}"
        )

    def action_back(self) -> None:
        self.dismiss(None)
