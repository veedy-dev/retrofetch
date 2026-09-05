"""BIOS opt-in download screen."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, ClassVar, cast

from textual import (
    work,  # pyright: ignore[reportMissingImports, reportAttributeAccessIssue]
)
from textual.app import ComposeResult  # pyright: ignore[reportMissingImports]
from textual.binding import Binding  # pyright: ignore[reportMissingImports]
from textual.containers import (  # pyright: ignore[reportMissingImports]
    ScrollableContainer,
    Vertical,
)
from textual.message import Message  # pyright: ignore[reportMissingImports]
from textual.screen import Screen  # pyright: ignore[reportMissingImports]
from textual.widgets import (  # pyright: ignore[reportMissingImports]
    Footer,
    Header,
    Label,
)

from retrofetch.sources import SourceUnavailable
from retrofetch.sources.bios import BiosFile, BiosSource

logger = logging.getLogger(__name__)


class BiosReady(Message):
    def __init__(self, console: str, files: list[BiosFile]) -> None:
        self.console = console
        self.files = files
        super().__init__()


class BiosFailed(Message):
    def __init__(self, console: str, reason: str) -> None:
        self.console = console
        self.reason = reason
        super().__init__()


class BiosDone(Message):
    def __init__(self, console: str, paths: list[Path]) -> None:
        self.console = console
        self.paths = paths
        super().__init__()


class BiosScreen(Screen[None]):
    BINDINGS: ClassVar[list[Binding]] = [
        Binding("enter", "download", "Download", show=True),
        Binding("escape", "back", "Back", show=True),
    ]

    source_factory: Any = BiosSource

    def __init__(self, *, console_entry: dict[str, Any]) -> None:
        super().__init__()
        self.console_entry = console_entry
        self.shortname = str(console_entry.get("shortname", "?"))
        self._files: list[BiosFile] = []
        self._loaded = False
        self._downloading = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Vertical(id="main-panel"):
            yield Label(
                f"BIOS: {self.shortname}. Enter=download to BIOS/{self.shortname}/, Esc=back.",
                id="bios-title",
            )
            yield Label("Loading BIOS sources...", id="bios-summary", markup=False)
            yield ScrollableContainer(id="bios-files")
        yield Footer()

    def on_mount(self) -> None:
        self._load_catalog()

    @work(thread=True, exclusive=True, group="bios-load")
    def _load_catalog(self) -> None:
        try:
            catalog = self.source_factory().list_files(self.shortname)
        except SourceUnavailable as exc:
            self.post_message(BiosFailed(self.shortname, str(exc)))
            return
        except Exception as exc:
            # Isolate provider failures without logging credential-bearing tracebacks.
            logger.exception("BIOS catalog failed: %s", type(exc).__name__, exc_info=False)
            self.post_message(BiosFailed(self.shortname, f"unexpected: {exc}"))
            return
        self.post_message(BiosReady(self.shortname, list(catalog.files)))

    def on_bios_ready(self, message: BiosReady) -> None:
        if message.console != self.shortname:
            return
        self._files = list(message.files)
        self._loaded = True
        container = self.query_one("#bios-files", ScrollableContainer)
        container.remove_children()
        for bios_file in self._files[:50]:
            size = f" ({bios_file.size} bytes)" if bios_file.size is not None else ""
            container.mount(Label(f"- {bios_file.filename}{size} [{bios_file.source}]"))
        if len(self._files) > 50:
            container.mount(Label(f"... and {len(self._files) - 50} more"))
        self.query_one("#bios-summary", Label).update(
            f"Ready: {len(self._files)} BIOS file(s). Press Enter to download."
        )

    def on_bios_failed(self, message: BiosFailed) -> None:
        if message.console != self.shortname:
            return
        if not self._downloading:
            self._files = []
            self._loaded = False
        self._downloading = False
        self.query_one("#bios-summary", Label).update(f"BIOS unavailable: {message.reason}")

    def action_download(self) -> None:
        if self._downloading:
            return
        if not self._loaded:
            self.query_one("#bios-summary", Label).update("BIOS list is still loading.")
            return
        if not self._files:
            self.query_one("#bios-summary", Label).update("No BIOS files available.")
            return
        self._downloading = True
        app = cast(Any, self.app)
        config = cast(Any, app.config)
        self.query_one("#bios-summary", Label).update(
            f"Downloading {len(self._files)} BIOS file(s) to {config.bios_root / self.shortname}..."
        )
        self._download_files()

    @work(thread=True, exclusive=True, group="bios-download")
    def _download_files(self) -> None:
        try:
            paths = self.source_factory().download(
                self.shortname,
                cast(Any, cast(Any, self.app).config).bios_root,
            )
        except Exception as exc:
            # Keep downloads isolated from the UI; raw tracebacks may contain secrets.
            logger.exception("BIOS download failed: %s", type(exc).__name__, exc_info=False)
            self.post_message(BiosFailed(self.shortname, f"download failed: {exc}"))
            return
        self.post_message(BiosDone(self.shortname, paths))

    def on_bios_done(self, message: BiosDone) -> None:
        if message.console != self.shortname:
            return
        self._downloading = False
        app = cast(Any, self.app)
        config = cast(Any, app.config)
        self.query_one("#bios-summary", Label).update(
            f"Done: {len(message.paths)} BIOS file(s) in {config.bios_root / self.shortname}."
        )

    def action_back(self) -> None:
        self.dismiss(None)
