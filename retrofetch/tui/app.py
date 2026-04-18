"""Retrofetch TUI application.

Constructed and launched from `retrofetch.cli::tui`. The application owns the
loaded configuration, consoles metadata, and overrides - screens access them
via `self.app.<attr>` without re-reading YAML from disk.

Exit code policy:
- 0: graceful quit via `q` binding
- 130: Ctrl+C -> Textual's SIGINT handler -> action_quit (T23 implements this)
- 2: raised by `cli.py::tui` preflight (NOT this module)
- 1: uncaught exception falls through Python

Shutdown decision tree (T23 - single Textual-native path):
- User presses `q` or Textual intercepts SIGINT -> `action_quit` below runs.
- `action_quit` cancels any in-flight `@work(group="download")` worker so the
  orchestrator observes its shared `stop_event` and persists state.json
  per-iteration (see DownloadWorker). We do NOT install a custom
  `signal.signal(SIGINT, ...)` handler - fighting Textual's SIGINT hook
  triggers the Textual-native blocking bug (issue #1707) and is forbidden
  by the plan's Must-NOT guardrail.
- After cancellation is observed (or after a 3s best-effort wait), we call
  `self.exit(0)`. Ctrl+C on POSIX still yields exit 130 at the interpreter
  layer because Textual's SIGINT path does not swallow the signal; on
  Windows, CTRL_BREAK_EVENT produces a platform-specific non-zero code.
"""
from __future__ import annotations

import asyncio as _asyncio
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

    async def action_quit(self) -> None:
        """Graceful teardown before exit.

        Cancels any in-flight 'download' worker group so the orchestrator can
        persist its state.json before the interpreter unwinds, then calls
        self.exit(0). Ctrl+C is handled natively by Textual's SIGINT hook
        which also routes through action_quit; we do not install our own
        signal handler (fighting Textual's causes issue #1707).
        """
        try:
            workers = list(self.workers._workers)  # pyright: ignore[reportAttributeAccessIssue]
        except Exception:
            workers = []
        download_workers = [
            w for w in workers if getattr(w, "group", None) == "download"
        ]
        if download_workers:
            try:
                self.workers.cancel_group(self, "download")
            except TypeError:
                try:
                    self.workers.cancel_group("download")  # type: ignore[call-arg]
                except Exception:
                    pass
            except Exception:
                pass
            for _ in range(30):
                await _asyncio.sleep(0.1)
                still_running = [w for w in download_workers if not w.is_finished]
                if not still_running:
                    break
        self.exit(0)

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
