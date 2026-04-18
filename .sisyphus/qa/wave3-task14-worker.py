"""Verify the download worker runs on a thread and posts DownloadComplete."""
from __future__ import annotations

import asyncio
import pathlib

from textual.app import App, ComposeResult  # pyright: ignore[reportMissingImports]
from textual.widgets import Static  # pyright: ignore[reportMissingImports]

from retrofetch.config import _yaml_rt, load_config
from retrofetch.tui.messages import DownloadComplete, DownloadCrashed
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

    def compose(self) -> ComposeResult:
        yield Static("worker harness")

    def on_mount(self) -> None:
        self.worker.start(
            console_entry=self._console_entry,
            wantlist=self._wantlist,
            config=self._config,
            allow_torrent=False,
            consoles_yml=self._consoles_yml,
            dry_run=True,
        )
        self.run_worker(self.worker.run, thread=True, exclusive=True, group="download")

    def on_download_complete(self, message: DownloadComplete) -> None:
        self.received.append(message)

    def on_download_crashed(self, message: DownloadCrashed) -> None:
        self.received.append(message)


async def main() -> None:
    config = load_config(pathlib.Path("config.yml.example"))
    consoles = _yaml_rt.load(pathlib.Path("consoles.yml").read_text(encoding="utf-8"))
    entry = next(c for c in consoles["consoles"] if c["shortname"] == "virtualboy")

    app = Harness(
        console_entry=entry,
        wantlist=["FakeGame 1", "FakeGame 2"],
        config=config,
        consoles_yml=consoles,
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.pause(5.0)
        assert any(isinstance(m, DownloadComplete) for m in app.received), (
            f"expected DownloadComplete, got {app.received}"
        )
        complete = next(m for m in app.received if isinstance(m, DownloadComplete))
        assert complete.report.console == "virtualboy"
        assert complete.report.attempted == 2
    print(
        f"T14 worker: OK (DownloadComplete for {complete.report.console}, attempted={complete.report.attempted})"
    )


asyncio.run(main())
