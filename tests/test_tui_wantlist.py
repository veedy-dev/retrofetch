from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from textual.app import App, ComposeResult
from textual.screen import Screen
from textual.widgets import Label

from retrofetch.config import Config, ConsoleOverride, _yaml_rt
from retrofetch.tui.screens.wantlist import WantlistScreen


class _HomeScreen(Screen[None]):
    def compose(self) -> ComposeResult:
        yield Label("home", id="home-label")


class _WantlistApp(App[None]):
    def __init__(self, screen: WantlistScreen) -> None:
        super().__init__()
        self.screen_to_push = screen
        self.config = Config(roms_root=Path("ROMs"), cache_dir=Path(".cache"))
        self.consoles_yml: dict[str, Any] = {"consoles": []}
        self.overrides: dict[str, ConsoleOverride] = {}

    async def on_mount(self) -> None:
        await self.push_screen(_HomeScreen())
        await self.push_screen(self.screen_to_push)


async def _wait_loaded(screen: WantlistScreen, pilot) -> None:
    for _ in range(50):
        if screen._loaded_source:
            return
        await pilot.pause(0.05)
    raise AssertionError("wantlist did not load")


def test_enter_saves_and_returns(monkeypatch, scratch_path) -> None:
    monkeypatch.chdir(scratch_path)
    Path("overrides.yml").write_text("consoles: {}\n", encoding="utf-8")
    monkeypatch.setattr(
        "retrofetch.tui.screens.wantlist.get_or_fetch_wantlist",
        lambda **kwargs: (["Burnout Dominator", "Ridge Racer"], False),
    )
    screen = WantlistScreen(
        console_entry={"shortname": "psp", "class": "B"},
        override=ConsoleOverride(),
    )
    app = _WantlistApp(screen)

    async def run() -> None:
        async with app.run_test() as pilot:
            await _wait_loaded(screen, pilot)
            await pilot.press("space")
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, _HomeScreen)

    asyncio.run(run())
    raw = _yaml_rt.load(Path("overrides.yml").read_text(encoding="utf-8"))
    assert raw["consoles"]["psp"]["include"] == ["Burnout Dominator"]


def test_s_key_no_longer_saves(monkeypatch, scratch_path) -> None:
    monkeypatch.chdir(scratch_path)
    Path("overrides.yml").write_text("consoles: {}\n", encoding="utf-8")
    before = Path("overrides.yml").read_text(encoding="utf-8")
    monkeypatch.setattr(
        "retrofetch.tui.screens.wantlist.get_or_fetch_wantlist",
        lambda **kwargs: (["Burnout Dominator", "Ridge Racer"], False),
    )
    screen = WantlistScreen(
        console_entry={"shortname": "psp", "class": "B"},
        override=ConsoleOverride(),
    )
    app = _WantlistApp(screen)

    async def run() -> None:
        async with app.run_test() as pilot:
            await _wait_loaded(screen, pilot)
            await pilot.press("space")
            await pilot.press("s")
            await pilot.pause()
            assert isinstance(app.screen, WantlistScreen)
            assert Path("overrides.yml").read_text(encoding="utf-8") == before
            await pilot.press("escape")
            await pilot.pause()

    asyncio.run(run())
    assert Path("overrides.yml").read_text(encoding="utf-8") == before
