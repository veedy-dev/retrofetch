"""Cancel confirm modal: prompts user before stopping a running download run."""
from __future__ import annotations

from textual.app import ComposeResult  # pyright: ignore[reportMissingImports]
from textual.binding import Binding  # pyright: ignore[reportMissingImports]
from textual.containers import Vertical  # pyright: ignore[reportMissingImports]
from textual.screen import ModalScreen  # pyright: ignore[reportMissingImports]
from textual.widgets import Label  # pyright: ignore[reportMissingImports]


class CancelConfirmScreen(ModalScreen[bool]):
    BINDINGS = [
        Binding("y", "confirm", "Yes", show=True),
        Binding("n", "decline", "No", show=True),
        Binding("escape", "decline", "No", show=True),
    ]

    def __init__(self, prompt: str = "Cancel running downloads? (y/n)") -> None:
        super().__init__()
        self._prompt = prompt

    def compose(self) -> ComposeResult:
        with Vertical(id="cancel-confirm-modal"):
            yield Label(self._prompt, id="cancel-confirm-question")
            yield Label("[y] Yes  [n] No  [esc] No", id="cancel-confirm-actions")

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_decline(self) -> None:
        self.dismiss(False)
