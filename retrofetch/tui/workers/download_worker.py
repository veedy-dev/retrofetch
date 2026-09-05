"""App-owned background run with a physical cleanup acknowledgement."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

from textual.message import Message

from retrofetch.config import Config
from retrofetch.events import EventBus
from retrofetch.orchestrator import run_console
from retrofetch.tui.messages import (
    DownloadComplete,
    DownloadCrashed,
    EventBusBridge,
    TorrentSetupRequired,
)

logger = logging.getLogger(__name__)


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
        return self.accepted and not (stop_event is not None and stop_event.is_set())


class DownloadWorker:
    """One run; receive must be thread-safe and target the owning app."""

    def __init__(self, receive: Callable[[Message], object]) -> None:
        self._receive = receive
        self.finished = threading.Event()
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
        self._bridge = EventBusBridge(self._receive, bus)
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
        """Publish the terminal result only after all run resources are closed."""
        result: Message
        try:
            if (
                self._console_entry is None
                or self._config is None
                or self._consoles_yml is None
                or self._bus is None
            ):
                raise RuntimeError("worker not initialized: call start() first")
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
            result = DownloadComplete(report)
        except Exception as exc:
            # Provider exception details may contain credentials; keep them out of logs.
            logger.exception(
                "Background download failed (%s)", type(exc).__name__, exc_info=False
            )
            result = DownloadCrashed(str(exc))
        finally:
            self._cleanup()
            self.finished.set()
        self._receive(result)

    def _request_torrent_setup(self) -> bool:
        gate = TorrentSetupGate()
        self._receive(TorrentSetupRequired(gate))
        return gate.wait(self._stop_event)

    def _cleanup(self) -> None:
        if self._bridge is not None:
            self._bridge.stop()
            self._bridge = None
