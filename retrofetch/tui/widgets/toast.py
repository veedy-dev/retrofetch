"""Non-blocking toast notifications — mount bottom-right, auto-dismiss after 3s."""
from __future__ import annotations

from typing import Literal

from textual.widget import Widget  # pyright: ignore[reportMissingImports]
from textual.widgets import Static  # pyright: ignore[reportMissingImports]


Severity = Literal["info", "warning", "error"]


class Toast(Static):
    DEFAULT_CSS = """
    Toast {
        background: $surface-darken-2;
        color: $text;
        padding: 1 2;
        margin: 1;
        border: round $primary;
        width: auto;
        height: auto;
    }
    Toast.toast-warning {
        border: round $warning;
        color: $warning;
    }
    Toast.toast-error {
        border: round $error;
        color: $error;
    }
    """

    def __init__(self, message: str, severity: Severity = "info") -> None:
        super().__init__(message)
        self.severity = severity
        self.add_class(f"toast-{severity}")

    def on_mount(self) -> None:
        self.set_timer(3.0, self._dismiss)

    def _dismiss(self) -> None:
        try:
            self.remove()
        except Exception:
            # race: toast may already be detached when timer fires
            pass
