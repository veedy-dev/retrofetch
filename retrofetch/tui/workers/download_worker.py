"""Threaded download worker for the TUI.

Runs orchestrator.run_console on a background thread. Forwards ProgressEvents
from the EventBus to Textual Messages via EventBusBridge, and posts
DownloadComplete / DownloadCrashed messages at the end of the run.

Thread-safety rules (Metis K.6, K.7):
- The enclosing screen applies `@work(thread=True, exclusive=True, group="download")`
  when invoking `run()` — we don't decorate methods here because @work lives on
  App/Screen methods, not arbitrary classes.
- No direct widget access from inside `run()`. Only `bus.publish` and
  `self._app.post_message` are safe from the worker thread.
- Exceptions inside `run()` are caught and posted as DownloadCrashed rather
  than propagated (Textual would swallow them silently).
- A shared `threading.Event` lets the main thread signal cancellation; the
  orchestrator already honors `stop_event` per-iteration (T10).
"""
from __future__ import annotations

import threading
from typing import Any

from textual.worker import get_current_worker  # pyright: ignore[reportMissingImports]

from retrofetch.config import Config
from retrofetch.events import EventBus
from retrofetch.orchestrator import RunReport, run_console
from retrofetch.tui.messages import (
    DownloadComplete,
    DownloadCrashed,
    EventBusBridge,
    TorrentSetupRequired,
)


class TorrentSetupGate:
    def __init__(self) -> None:
        self._event = threading.Event()
        self.accepted = False

    def resolve(self, accepted: bool) -> None:
        self.accepted = bool(accepted)
        self._event.set()

    def wait(self, stop_event: threading.Event | None) -> bool:
        if stop_event is not None and stop_event.is_set():
            return False
        while not self._event.wait(0.1):
            if stop_event is not None and stop_event.is_set():
                return False
        return self.accepted and not (
            stop_event is not None and stop_event.is_set()
        )


class DownloadWorker:
    """Owns the lifecycle of a download run for one console.

    Usage from a Screen:

        self.worker = DownloadWorker(self.app)
        stop_event = self.worker.start(console_entry=..., wantlist=..., config=..., ...)
        self.run_worker(self.worker.run, thread=True, exclusive=True, group="download")
        # later, to cancel:
        stop_event.set()
    """

    def __init__(self, app) -> None:
        self._app = app
        self._bridge: EventBusBridge | None = None
        self._stop_event: threading.Event | None = None
        self._bus: EventBus | None = None
        self._console_entry: dict[str, Any] | None = None
        self._wantlist: list[str] = []
        self._config: Config | None = None
        self._allow_torrent: bool = True
        self._consoles_yml: dict[str, Any] | None = None
        self._dry_run: bool = False

    def start(
        self,
        *,
        console_entry: dict[str, Any],
        wantlist: list[str],
        config: Config,
        allow_torrent: bool,
        consoles_yml: dict[str, Any],
        dry_run: bool = False,
    ) -> threading.Event:
        """Wire bridge + EventBus on the main thread."""
        bus = EventBus()
        self._bridge = EventBusBridge(self._app, bus)
        self._bridge.start()
        self._stop_event = threading.Event()
        self._bus = bus
        self._console_entry = console_entry
        self._wantlist = wantlist
        self._config = config
        self._allow_torrent = allow_torrent
        self._consoles_yml = consoles_yml
        self._dry_run = dry_run
        return self._stop_event

    def run(self) -> None:
        """Blocking method called on the worker thread."""
        if (
            self._console_entry is None
            or self._config is None
            or self._consoles_yml is None
            or self._bus is None
        ):
            self._app.post_message(DownloadCrashed("worker not initialized: call start() first"))
            return

        report: RunReport | None = None
        try:
            current = get_current_worker()
            if current is not None and current.is_cancelled and self._stop_event is not None:
                self._stop_event.set()
            report = run_console(
                console_entry=self._console_entry,
                wantlist=self._wantlist,
                config=self._config,
                allow_torrent=self._allow_torrent,
                consoles_yml=self._consoles_yml,
                stop_event=self._stop_event,
                event_bus=self._bus,
                dry_run=self._dry_run,
                torrent_setup_callback=self._request_torrent_setup,
            )
        except Exception as exc:
            try:
                self._app.post_message(DownloadCrashed(str(exc)))
            finally:
                self._cleanup()
            return

        try:
            if report is not None:
                self._app.post_message(DownloadComplete(report))
        finally:
            self._cleanup()

    def _request_torrent_setup(self) -> bool:
        gate = TorrentSetupGate()
        self._app.post_message(TorrentSetupRequired(gate))
        return gate.wait(self._stop_event)

    def _cleanup(self) -> None:
        if self._bridge is not None:
            self._bridge.stop()
            self._bridge = None
