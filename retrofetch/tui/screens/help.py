"""Help modal — global bindings and per-screen hints."""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult  # pyright: ignore[reportMissingImports]
from textual.binding import Binding  # pyright: ignore[reportMissingImports]
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen  # pyright: ignore[reportMissingImports]
from textual.widgets import Label, Static  # pyright: ignore[reportMissingImports]

HELP_TEXT = """Browse consoles
  Enter / g  browse games for the highlighted console
  /          search consoles
  d          review the queue for this console
  s          download history
  Left/Right previous / next preview page
  r          refresh the catalog
  b          optional BIOS downloads
  ,          settings
  C          coverage report

Choose games
  Space      add to / remove from the queue
  /          search titles
  Enter      focus results from search; otherwise review queue
  s          show queued games / all results
  Ctrl+A     queue all search results
  Ctrl+U     remove search results from the queue
  x          exclude / restore the highlighted title
  PgUp/PgDn  previous / next page
  Esc        return to results from search, then go back

Queue
  Enter      start the selected downloads
  x / Delete remove the highlighted game from the queue
  Esc        go back; queue changes are kept

Downloads
  F6         open current downloads from any screen
  Esc        keep downloading and return to browsing
  c          ask to cancel remaining downloads
  v          show / hide verification and provider details
  h          open saved download history

Background downloads continue while Retrofetch is open.
Completed files leave the queue and remain in History.
Failed and cancelled games stay queued for another attempt.
Selections are session-only; reopening starts a fresh queue.

General
  Tab        move between controls
  ?          open / close this help
  q / Ctrl+Q quit; active downloads require confirmation
  Ctrl+C     the same safe quit flow

Settings: Ctrl+S saves; Esc returns without saving.
Torrent setup: Enter chooses an option; Esc defers setup.
History: r refreshes; arrows show the selected file details."""


class HelpScreen(ModalScreen[None]):
    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "close", "Close", show=True),
        Binding("question_mark", "close", "Close", show=True, key_display="?"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="help-panel"):
            yield Label("Keyboard shortcuts", id="help-title")
            with VerticalScroll(id="help-scroll"):
                yield Static(HELP_TEXT, id="help-body", markup=False)
            yield Label("Esc or ?  Close help", id="help-footer")

    def action_close(self) -> None:
        self.dismiss(None)
