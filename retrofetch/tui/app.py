"""Retrofetch TUI application.

Constructed and launched from `retrofetch.cli::tui`. The application owns the
loaded configuration, consoles metadata, and overrides - screens access them
via `self.app.<attr>` without re-reading YAML from disk.

Exit code policy:
- 0: graceful quit via `q` binding (``action_quit`` -> ``self.exit(0)``)
- 130: SIGINT / Ctrl+C on POSIX -> handled natively by Textual's SIGINT hook.
  The Python interpreter unwinds with the signal exit code (130 on POSIX); on
  Windows CTRL_BREAK_EVENT produces a platform-specific non-zero code.
- 2: raised by `cli.py::tui` preflight (NOT this module)
- 1: uncaught exception falls through Python

Shutdown decision tree (T23 - single Textual-native path):
- User presses `q` -> ``action_quit`` below runs -> ``self.exit(0)``.
- SIGINT / Ctrl+C -> handled natively by Textual's SIGINT hook. We intentionally
  avoid installing our own SIGINT handler (fighting Textual's handler causes
  issue #1707, banned by the plan's Must-NOT guardrail). We also do not call
  ``ShutdownCoordinator.install()`` in the TUI path for the same reason; the
  orchestrator's worker-group cancellation is sufficient.
- ``action_quit`` cancels any in-flight `@work(group="download")` worker so the
  orchestrator observes its shared `stop_event` and persists state.json
  per-iteration (see DownloadWorker). After cancellation is observed (or
  after a 3s best-effort wait), we call ``self.exit(0)``.
"""

from __future__ import annotations

import asyncio as _asyncio
from pathlib import Path
from typing import Any

from textual.app import App  # pyright: ignore[reportMissingImports]

from retrofetch.config import (
    Config,
    ConfigError,
    ConsoleOverride,
    load_config,
    load_overrides,
)
from retrofetch.wantlist_cache import invalidate_all


class RetrofetchApp(App[int]):
    CSS_PATH = "styles.tcss"
    TITLE = "Retrofetch"
    SUB_TITLE = "retro library manager"

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
        overrides_path: Path | None = None,
        first_run: bool = False,
    ) -> None:
        super().__init__()
        self.config = config
        self.config_path = config_path
        self.overrides_path = overrides_path or config_path.with_name("overrides.yml")
        self.consoles_yml = consoles_yml
        self.overrides = overrides
        self._first_run = first_run

    def on_mount(self) -> None:
        if self._first_run:
            from retrofetch.tui.screens.setup import SetupScreen

            def _on_setup_done(result: bool | None) -> None:
                if not result:
                    self.exit(2)
                    return
                try:
                    self.config = load_config(self.config_path)
                except ConfigError:
                    self.exit(2)
                    return
                try:
                    self.overrides = load_overrides(self.overrides_path)
                except ConfigError:
                    self.overrides = {}
                self._open_fresh_home()

            self.push_screen(
                SetupScreen(config_path=self.config_path, defaults=self.config),
                _on_setup_done,
            )
        else:
            self._open_fresh_home()

    def _open_fresh_home(self) -> None:
        invalidate_all(self.config.cache_dir)
        self.overrides = {
            shortname: override.model_copy(update={"include": [], "exclude": []})
            for shortname, override in self.overrides.items()
        }
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
            # Textual API compat: private _workers attribute may differ between releases
            workers = []
        if any(
            getattr(worker, "group", None) == "torrent-install"
            and not worker.is_finished
            for worker in workers
        ):
            self.show_toast(
                "qBittorrent setup is still running; quit after it finishes.",
                "warning",
            )
            return
        download_workers = [
            w for w in workers if getattr(w, "group", None) == "download"
        ]
        if download_workers:
            for screen in tuple(self.screen_stack):
                stop_event = getattr(screen, "_stop_event", None)
                if stop_event is not None:
                    stop_event.set()
            try:
                self.workers.cancel_group(self, "download")
            except TypeError:
                try:
                    self.workers.cancel_group("download")  # type: ignore[call-arg]
                except Exception:
                    # Textual API compat: cancel_group signature varies between releases
                    pass
            except Exception:
                # shutdown race: worker group may already be cancelled by Textual
                pass
            still_running = download_workers
            for _ in range(80):
                await _asyncio.sleep(0.1)
                still_running = [w for w in download_workers if not w.is_finished]
                if not still_running:
                    break
            if still_running:
                self.show_toast(
                    "Downloads are still stopping safely; press Quit again after cleanup.",
                    "warning",
                )
                return
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
            # shutdown race: toast container may already be unmounted
            pass
