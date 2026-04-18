"""Verify cancellation: stop_event.set() causes orchestrator to stop promptly."""
from __future__ import annotations

import asyncio
import pathlib
import threading

from textual.app import App, ComposeResult  # pyright: ignore[reportMissingImports]
from textual.widgets import Static  # pyright: ignore[reportMissingImports]

from retrofetch.config import _yaml_rt, load_config
from retrofetch.tui.messages import DownloadComplete
from retrofetch.tui.workers.download_worker import DownloadWorker


class Harness(App[int]):
    def __init__(self, *, console_entry, wantlist, config, consoles_yml) -> None:
        super().__init__()
        self.received: list = []
        self._console_entry = console_entry
        self._wantlist = wantlist
        self._config = config
        self._consoles_yml = consoles_yml
        self.worker = DownloadWorker(self)
        self.stop_event: threading.Event | None = None

    def compose(self) -> ComposeResult:
        yield Static("cancel harness")

    def on_mount(self) -> None:
        self.stop_event = self.worker.start(
            console_entry=self._console_entry,
            wantlist=self._wantlist,
            config=self._config,
            allow_torrent=False,
            consoles_yml=self._consoles_yml,
            dry_run=True,
        )
        assert self.stop_event is not None
        self.stop_event.set()
        self.run_worker(self.worker.run, thread=True, exclusive=True, group="download")

    def on_download_complete(self, message: DownloadComplete) -> None:
        self.received.append(message)


async def main() -> None:
    config = load_config(pathlib.Path("config.yml.example"))
    consoles = _yaml_rt.load(pathlib.Path("consoles.yml").read_text(encoding="utf-8"))
    entry = next(c for c in consoles["consoles"] if c["shortname"] == "virtualboy")

    wantlist = [f"FakeGame {i}" for i in range(100)]
    app = Harness(console_entry=entry, wantlist=wantlist, config=config, consoles_yml=consoles)

    async with app.run_test() as pilot:
        await pilot.pause(3.0)

        assert any(isinstance(m, DownloadComplete) for m in app.received), (
            f"expected DownloadComplete even after cancel, got {app.received}"
        )
        report = next(m.report for m in app.received if isinstance(m, DownloadComplete))
        assert report.attempted < 100, f"expected <100 attempted (cancelled), got {report.attempted}"
    print(f"T14 cancel: OK (cancelled after {report.attempted}/100 entries)")


asyncio.run(main())
