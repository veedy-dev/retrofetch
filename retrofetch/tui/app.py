"""Retrofetch TUI application.

Constructed and launched from `retrofetch.cli::tui`. The application owns the
loaded configuration, consoles metadata, and overrides — screens access them
via `self.app.<attr>` without re-reading YAML from disk.

Exit code policy:
- 0: graceful quit via `q` binding
- 130: Ctrl+C → Textual's SIGINT handler → action_quit (T23 implements this)
- 2: raised by `cli.py::tui` preflight (NOT this module)
- 1: uncaught exception falls through Python
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from textual.app import App  # pyright: ignore[reportMissingImports]

from retrofetch.config import Config, ConsoleOverride


class RetrofetchApp(App[int]):
    CSS_PATH = "styles.tcss"

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("question_mark", "help", "Help"),
    ]

    def __init__(
        self,
        *,
        config: Config,
        config_path: Path,
        consoles_yml: dict[str, Any],
        overrides: dict[str, ConsoleOverride],
    ) -> None:
        super().__init__()
        self.config = config
        self.config_path = config_path
        self.consoles_yml = consoles_yml
        self.overrides = overrides

    def on_mount(self) -> None:
        from retrofetch.tui.screens.home import HomeScreen
        self.push_screen(HomeScreen())

    def action_help(self) -> None:
        from retrofetch.tui.screens.help import HelpScreen
        self.push_screen(HelpScreen())

    def show_toast(self, message: str, severity: str = "info") -> None:
        """Display a non-blocking toast at the bottom-right for 3s.

        Called from any screen/handler. Severity: 'info' | 'warning' | 'error'.
        """
        from retrofetch.tui.widgets.toast import Toast, Severity
        sev: Severity = severity if severity in ("info", "warning", "error") else "info"  # type: ignore[assignment]
        try:
            toast = Toast(message, severity=sev)
            self.mount(toast)
        except Exception:
            pass
