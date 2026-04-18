"""Coverage viewer screen — async compute + DataTable + markdown export."""
from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult  # pyright: ignore[reportMissingImports]
from textual.binding import Binding  # pyright: ignore[reportMissingImports]
from textual.containers import Vertical  # pyright: ignore[reportMissingImports]
from textual.screen import Screen  # pyright: ignore[reportMissingImports]
from textual.widgets import DataTable, Footer, Header, Label  # pyright: ignore[reportMissingImports]
from textual import work  # pyright: ignore[reportMissingImports]

from retrofetch.coverage import CoverageReport, compute_coverage
from retrofetch.report import write_coverage_markdown
from retrofetch.tui.messages import CoverageReady


class CoverageScreen(Screen[None]):
    BINDINGS = [
        Binding("e", "export", "Export", show=True),
        Binding("escape", "back", "Back", show=True),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._report: CoverageReport | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Vertical(id="main-panel"):
            yield Label("Coverage (computing...). e=export, esc=back.", id="cov-title")
            yield DataTable(id="coverage-table")
        yield Footer()

    def on_mount(self) -> None:
        table: DataTable = self.query_one("#coverage-table", DataTable)
        table.add_columns("Console", "Class", "Target", "Acquired", "Unverified", "Failed", "% Complete")
        table.cursor_type = "row"
        self._kick_compute()

    @work(thread=True, exclusive=True, group="coverage")
    def _kick_compute(self) -> None:
        consoles_yml_path = Path("consoles.yml")
        if not consoles_yml_path.exists():
            from retrofetch.cli import _REPO_DIR
            consoles_yml_path = _REPO_DIR / "consoles.yml"
        roms_root = self.app.config.roms_root  # pyright: ignore[reportAttributeAccessIssue]
        report = compute_coverage(consoles_yml_path, roms_root)
        self.post_message(CoverageReady(report))

    def on_coverage_ready(self, message: CoverageReady) -> None:
        self._report = message.report
        table: DataTable = self.query_one("#coverage-table", DataTable)
        table.clear()
        for c in message.report.by_console:
            target = c.target
            pct = 0.0 if target == 0 else (100.0 * c.acquired / target)
            table.add_row(
                c.shortname,
                c.class_,
                str(target),
                str(c.acquired),
                str(c.unverified),
                str(c.failed),
                f"{pct:.1f}%",
            )
        self.query_one("#cov-title", Label).update(
            f"Coverage: {len(message.report.by_console)} consoles. e=export, esc=back."
        )

    def action_export(self) -> None:
        if self._report is None:
            return
        out = Path.cwd() / "coverage.md"
        write_coverage_markdown(self._report, out)
        self.query_one("#cov-title", Label).update(
            f"Exported to {out}. e=export, esc=back."
        )

    def action_back(self) -> None:
        self.dismiss(None)
