from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from textual.app import App

from retrofetch.config import Config, ConsoleOverride
from retrofetch.sources.bios import BiosFile
from retrofetch.tui.screens.bios import BiosScreen
from retrofetch.tui.screens.download_confirm import DownloadConfirmScreen
from retrofetch.tui.screens.download_progress import DownloadProgressScreen
from retrofetch.tui.screens.home import HomeScreen


class _TuiApp(App[None]):
    def __init__(self, screen) -> None:
        super().__init__()
        self.screen_to_push = screen
        self.config = Config(roms_root=Path("ROMs"), bios_root=Path("BIOS"))
        self.consoles_yml: dict[str, Any] = {"consoles": []}
        self.overrides: dict[str, ConsoleOverride] = {}

    async def on_mount(self) -> None:
        await self.push_screen(self.screen_to_push)


def test_home_availability_accepts_minerva_only_source() -> None:
    assert HomeScreen._is_available(
        {"shortname": "minervaonly", "class": "A", "minerva_path": "No-Intro/Test"}
    )


def test_download_confirm_has_no_tui_dry_run_and_starts_real(monkeypatch) -> None:
    monkeypatch.setattr(
        "retrofetch.tui.screens.download_confirm.get_or_fetch_wantlist",
        lambda **kwargs: (["A", "B"], False),
    )
    screen = DownloadConfirmScreen(
        console_entry={"shortname": "nes", "class": "A"},
        override=ConsoleOverride(include=["B"]),
    )
    app = _TuiApp(screen)

    async def run() -> None:
        async with app.run_test() as pilot:
            for _ in range(50):
                if screen._loaded:
                    break
                await pilot.pause(0.05)
            assert screen._wantlist == ["B"]
            assert not screen.query("#dry-run-toggle")
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, DownloadProgressScreen)
            assert app.screen.dry_run is False

    asyncio.run(run())


def test_bios_screen_lists_and_downloads(monkeypatch, scratch_path) -> None:
    class _FakeBiosSource:
        def list_files(self, console: str):
            return SimpleNamespace(
                files=[
                    BiosFile(console, "scph5501.bin", "https://example/scph5501.bin", 10, "archive_org")
                ]
            )

        def download(self, console: str, root: Path):
            target = root / console
            target.mkdir(parents=True, exist_ok=True)
            path = target / "scph5501.bin"
            path.write_bytes(b"bios")
            return [path]

    screen = BiosScreen(console_entry={"shortname": "psx", "class": "B"})
    screen.source_factory = _FakeBiosSource  # type: ignore[assignment]
    app = _TuiApp(screen)
    app.config = Config(roms_root=scratch_path / "ROMs", bios_root=scratch_path / "BIOS")

    async def run() -> None:
        async with app.run_test() as pilot:
            for _ in range(50):
                if screen._loaded:
                    break
                await pilot.pause(0.05)
            assert len(screen._files) == 1
            await pilot.press("enter")
            for _ in range(50):
                if (scratch_path / "BIOS" / "psx" / "scph5501.bin").exists():
                    break
                await pilot.pause(0.05)
            assert (scratch_path / "BIOS" / "psx" / "scph5501.bin").read_bytes() == b"bios"

    asyncio.run(run())
