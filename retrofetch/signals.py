"""Signal handlers for graceful shutdown."""

from __future__ import annotations

import logging
import signal
import threading

_log = logging.getLogger(__name__)


class ShutdownCoordinator:
    def __init__(self) -> None:
        self.stop_event = threading.Event()
        self._handlers_installed = False

    def request_stop(self, signum: int | None = None, frame: Any = None) -> None:
        if not self.stop_event.is_set():
            _log.warning(
                "shutdown requested (signal=%s); finishing current task", signum
            )
        self.stop_event.set()

    def install(self) -> None:
        if self._handlers_installed:
            return
        for sig_name in ("SIGINT", "SIGTERM", "SIGBREAK"):
            sig = getattr(signal, sig_name, None)
            if sig is None:
                continue
            try:
                signal.signal(sig, self.request_stop)
            except (OSError, ValueError):
                pass
        self._handlers_installed = True


_global_coordinator: ShutdownCoordinator | None = None


def install_signal_handlers() -> ShutdownCoordinator:
    global _global_coordinator
    if _global_coordinator is None:
        _global_coordinator = ShutdownCoordinator()
        _global_coordinator.install()
    return _global_coordinator


def stop_event() -> threading.Event:
    return install_signal_handlers().stop_event


from typing import Any
