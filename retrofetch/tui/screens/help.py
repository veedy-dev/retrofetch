"""Help modal — global bindings and per-screen hints."""
from __future__ import annotations

from textual.app import ComposeResult  # pyright: ignore[reportMissingImports]
from textual.binding import Binding  # pyright: ignore[reportMissingImports]
from textual.containers import Vertical  # pyright: ignore[reportMissingImports]
from textual.screen import ModalScreen  # pyright: ignore[reportMissingImports]
from textual.widgets import Label, Static  # pyright: ignore[reportMissingImports]


HELP_TEXT = """Retrofetch TUI - keyboard reference

Global
  q          quit
  ?          toggle this help
  /          focus the filter input (Home)
  tab        cycle focus

Home screen
  j / down   next console
  k / up     prev console
  enter      select console
  w          wantlist curation
  d          download screen
  b          BIOS download screen
  s          state browser
  C          coverage viewer
  Ctrl+R     retry fetch (invalidate cache + re-fetch)
  [          previous page in preview
  ]          next page in preview

Sidebar color legend
  green      console has a ranking provider (you can browse games)
  grey       no provider for this console - skipped or unsupported

Editors
  Ctrl+S     save
  Esc        cancel

Download screen
  Enter      start download
  c          cancel in-flight download
  Esc        back to Home

Wantlist screen
  Space      include / uninclude selected title
  x          exclude / unexclude selected title
  Enter      save and return to Home
  Esc        cancel without saving

BIOS screen
  Enter      download BIOS files to BIOS/<console>/
  Esc        back to Home

Exit codes
  0          graceful quit
  2          preflight failure (bad terminal, missing config)
  130        Ctrl+C"""


class HelpScreen(ModalScreen[None]):
    BINDINGS = [
        Binding("escape", "close", "Close", show=True),
        Binding("question_mark", "close", "Close", show=True, key_display="?"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="help-panel"):
            yield Label("retrofetch help", id="help-title")
            yield Static(HELP_TEXT, id="help-body")
            yield Label("press esc or ? to close", id="help-footer")

    def action_close(self) -> None:
        self.dismiss(None)
