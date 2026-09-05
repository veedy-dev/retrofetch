"""Application-owned configuration, selections and background download lifecycle.

Quit requests cooperative cancellation and waits up to eight seconds for actual
resource cleanup. Leaving a screen never cancels a download.
"""

from __future__ import annotations

import asyncio as _asyncio
import threading
from pathlib import Path
from typing import Any, ClassVar

from textual.app import App  # pyright: ignore[reportMissingImports]
from textual.binding import Binding, BindingType

from retrofetch.config import (
    Config,
    ConfigError,
    ConsoleOverride,
    load_config,
    load_overrides,
)
from retrofetch.tui.downloads import DownloadSession, format_speed
from retrofetch.tui.messages import (
    DownloadComplete,
    DownloadCrashed,
    DownloadUpdate,
    GameDone,
    GameSkipped,
    GameUnverified,
    QueueChanged,
    TorrentSetupRequired,
)
from retrofetch.tui.workers.download_worker import DownloadWorker, TorrentSetupGate


class RetrofetchApp(App[int]):
    CSS_PATH = "styles.tcss"
    TITLE = "Retrofetch"
    SUB_TITLE = "retro library manager"

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("q", "quit", "Quit"),
        Binding("ctrl+c", "quit", "Quit", show=False, priority=True),
        Binding("f6", "downloads", "Downloads", priority=True),
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
        self.download_session: DownloadSession | None = None
        self._download_worker: DownloadWorker | None = None
        self._stop_event: threading.Event | None = None
        self._setup_request: TorrentSetupGate | None = None
        self._catalog_sub_title: str = "retro library manager"
        self._quit_pending = False

    def on_mount(self) -> None:
        self.set_interval(0.25, self._refresh_download_header)
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
        self.overrides = {
            shortname: override.model_copy(update={"include": [], "exclude": []})
            for shortname, override in self.overrides.items()
        }
        from retrofetch.tui.screens.home import HomeScreen

        self.push_screen(HomeScreen())

    def action_help(self) -> None:
        from retrofetch.tui.screens.help import HelpScreen

        self.push_screen(HelpScreen())

    def start_download(
        self,
        console_entry: dict[str, Any],
        wantlist: list[str],
        *,
        dry_run: bool = False,
    ) -> bool:
        if (
            self._download_worker is not None
            and not self._download_worker.finished.is_set()
        ):
            self.show_toast(
                "A download batch is already running. F6 opens its progress.", "warning"
            )
            return False
        if self.download_session is not None and self.download_session.running:
            self.show_toast(
                "Finishing the previous batch; try again shortly.", "warning"
            )
            return False
        if not wantlist:
            self.show_toast("Choose games before starting a download.")
            return False
        session = DownloadSession(dict(console_entry), list(wantlist), dry_run)
        worker = DownloadWorker(
            lambda message: self.post_message(DownloadUpdate(session, message))
        )
        self._stop_event = worker.start(
            console_entry=session.console_entry,
            wantlist=session.wantlist,
            config=self.config.model_copy(update={"dry_run": dry_run}),
            allow_torrent=True,
            consoles_yml=self.consoles_yml,
            dry_run=dry_run,
        )
        self.download_session = session
        self._download_worker = worker
        self.run_worker(worker.run, thread=True, group="download", exit_on_error=False)
        self._refresh_download_header()
        return True

    def action_downloads(self) -> None:
        from retrofetch.tui.screens.download_progress import DownloadProgressScreen

        if self.download_session is None:
            self.show_toast(
                "No downloads yet. Choose games and review your queue first."
            )
            return
        if any(
            isinstance(screen, DownloadProgressScreen) for screen in self.screen_stack
        ):
            if not isinstance(self.screen, DownloadProgressScreen):
                self.show_toast(
                    "Downloads are open underneath this screen; Esc returns there."
                )
            else:
                self.download_session.unread = False
                self._refresh_download_header()
            return
        self.download_session.unread = False
        self.push_screen(DownloadProgressScreen())
        self._refresh_download_header()

    def update_selection(
        self, shortname: str, include: list[str], exclude: list[str]
    ) -> None:
        current = self.overrides.get(shortname, ConsoleOverride())
        self.overrides[shortname] = current.model_copy(
            update={"include": list(include), "exclude": list(exclude)}
        )
        for screen in self.screen_stack:
            screen.post_message(QueueChanged(shortname))

    def set_catalog_sub_title(self, text: str) -> None:
        self._catalog_sub_title = text
        self._refresh_download_header()

    def _refresh_download_header(self) -> None:
        session = self.download_session
        self.set_class(bool(session and session.running), "download-running")
        self.set_class(
            bool(
                session
                and session.unread
                and not session.running
                and (session.failed or session.error)
            ),
            "download-attention",
        )
        if session is not None and session.running:
            speed = format_speed(
                sum(item.speed_bps for item in session.active.values())
            )
            phase = "Stopping" if session.cancelling else "Downloads"
            self.sub_title = f"F6 {phase} | {session.shortname} {session.processed_count}/{len(session.wantlist)} | {speed}"
        elif session is not None and session.unread:
            self.sub_title = f"F6 Downloads | {session.shortname}: {session.summary}"
        else:
            self.sub_title = self._catalog_sub_title

    def on_download_update(self, update: DownloadUpdate) -> None:
        update.stop()
        session, message = update.session, update.message
        if session is not self.download_session or not session.running:
            if isinstance(message, TorrentSetupRequired):
                message.request.resolve(False)
            return
        if isinstance(message, TorrentSetupRequired):
            self._request_torrent_setup(message)
            return
        previous = session.history_revision
        session.apply(message)
        if (
            session.history_revision != previous
            and not session.dry_run
            and (
                (
                    isinstance(message, (GameDone, GameUnverified))
                    and message.source != "dry-run"
                )
                or (isinstance(message, GameSkipped) and bool(message.filename))
            )
        ):
            current = self.overrides.get(session.shortname, ConsoleOverride())
            self.update_selection(
                session.shortname,
                [title for title in current.include if title != message.game],
                current.exclude,
            )
        if isinstance(message, (DownloadComplete, DownloadCrashed)):
            from retrofetch.tui.screens.download_progress import DownloadProgressScreen

            if isinstance(self.screen, DownloadProgressScreen):
                session.unread = False
            self._decline_setup()
            self.show_toast(
                f"{session.shortname}: {session.summary} F6 opens downloads.",
                "error" if session.error or session.failed else "information",
            )

    def _request_torrent_setup(self, message: TorrentSetupRequired) -> None:
        from retrofetch.tui.screens.torrent_setup import TorrentSetupScreen

        if (
            self._setup_request is not None
            or self._stop_event is None
            or self._stop_event.is_set()
        ):
            message.request.resolve(False)
            return
        request = message.request
        self._setup_request = request

        def resolved(result: bool | None) -> None:
            if self._setup_request is request:
                self._setup_request = None
                request.resolve(
                    result is True
                    and self._stop_event is not None
                    and not self._stop_event.is_set()
                )

        self.push_screen(
            TorrentSetupScreen(qbittorrent_path=self.config.qbittorrent_path), resolved
        )

    def _decline_setup(self) -> None:
        if self._setup_request is not None:
            self._setup_request.resolve(False)
            self._setup_request = None

    def cancel_download(self) -> None:
        if self._download_worker is None or self._download_worker.finished.is_set():
            return
        if self._stop_event is not None:
            self._stop_event.set()
        self._decline_setup()
        if self.download_session is not None:
            self.download_session.cancelling = True
            self.download_session.revision += 1

    async def action_quit(self) -> None:
        if self._quit_pending:
            return
        if any(
            worker.group == "torrent-install" and not worker.is_finished
            for worker in self.workers
        ):
            self.show_toast(
                "qBittorrent setup is still running; quit after it finishes.", "warning"
            )
            return
        if (
            self._download_worker is not None
            and not self._download_worker.finished.is_set()
        ):
            from retrofetch.tui.screens.cancel_confirm import CancelConfirmScreen

            self._quit_pending = True

            def confirmed(result: bool | None) -> None:
                if result is True:
                    self.run_worker(self._finish_quit(), group="quit")
                else:
                    self._quit_pending = False

            self.push_screen(
                CancelConfirmScreen("Stop downloads safely and quit? (y/n)"), confirmed
            )
            return
        self._decline_setup()
        self.exit(0)

    async def _finish_quit(self) -> None:
        self.cancel_download()
        worker = self._download_worker
        for _ in range(80):
            if worker is None or worker.finished.is_set():
                self.exit(0)
                return
            await _asyncio.sleep(0.1)
        self._quit_pending = False
        self.show_toast(
            "Downloads are still stopping safely; quit again after cleanup.", "warning"
        )

    def on_unmount(self) -> None:
        self.cancel_download()
        self._decline_setup()

    def show_toast(self, message: str, severity: str = "info") -> None:
        level = (
            "error"
            if severity == "error"
            else "warning"
            if severity == "warning"
            else "information"
        )
        self.notify(message, severity=level, timeout=5, markup=False)
