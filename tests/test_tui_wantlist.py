from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from textual.app import App, ComposeResult
from textual.screen import Screen
from textual.widgets import DataTable, Label

from retrofetch.config import Config, ConsoleOverride
from retrofetch.tui.screens.download_confirm import DownloadConfirmScreen
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
        if screen._loaded:
            return
        await pilot.pause(0.05)
    raise AssertionError("wantlist did not load")


def test_enter_applies_for_session_and_returns(monkeypatch, scratch_path) -> None:
    monkeypatch.chdir(scratch_path)
    assert all(
        getattr(binding, "key", None) != "s" for binding in WantlistScreen.BINDINGS
    )
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
            assert app.overrides["psp"].include == ["Burnout Dominator"]

    asyncio.run(run())
    assert not Path("overrides.yml").exists()


def test_s_key_no_longer_saves(monkeypatch, scratch_path) -> None:
    monkeypatch.chdir(scratch_path)
    assert all(
        getattr(binding, "key", None) != "s" for binding in WantlistScreen.BINDINGS
    )
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
            assert app.overrides == {}
            await pilot.press("escape")
            await pilot.pause()

    asyncio.run(run())
    assert not Path("overrides.yml").exists()


def test_large_catalog_filter_preserves_selection(monkeypatch, scratch_path) -> None:
    monkeypatch.chdir(scratch_path)
    titles = [f"Game {i:04d}" for i in range(2988)] + [
        f"Mario Adventure {i:02d}" for i in range(12)
    ]
    monkeypatch.setattr(
        "retrofetch.tui.screens.wantlist.get_or_fetch_wantlist",
        lambda **kwargs: (titles, False),
    )
    screen = WantlistScreen(
        console_entry={"shortname": "snes", "class": "A"},
        override=ConsoleOverride(),
    )
    app = _WantlistApp(screen)

    async def run() -> None:
        async with app.run_test() as pilot:
            await _wait_loaded(screen, pilot)
            assert len(screen._wantlist) == 3000
            await pilot.press("/")
            await pilot.press(*list("mario"))
            await pilot.pause()
            assert len(screen._filtered_wantlist) == 12
            screen.query_one("#wantlist-table").focus()
            await pilot.press("space")
            assert len(screen._include) == 1
            screen.action_page_next()
            assert screen._page == 0
            assert screen.query_one("#wantlist-table", DataTable).row_count == 12
            assert len(screen._include) == 1

    asyncio.run(run())


def test_apply_updates_runtime_selection_used_by_download(
    monkeypatch, scratch_path
) -> None:
    monkeypatch.chdir(scratch_path)
    titles = ["FIFA", "Ben 10", "Naruto Shippuden - Kizuna Drive"]
    monkeypatch.setattr(
        "retrofetch.tui.screens.wantlist.get_or_fetch_wantlist",
        lambda **kwargs: (titles, True),
    )
    monkeypatch.setattr(
        "retrofetch.tui.screens.download_confirm.get_or_fetch_wantlist",
        lambda **kwargs: (titles, True),
    )
    initial = ConsoleOverride(include=["FIFA", "Ben 10"])
    screen = WantlistScreen(
        console_entry={"shortname": "psp", "class": "B"},
        override=initial,
    )
    app = _WantlistApp(screen)
    app.overrides["psp"] = initial

    async def run() -> None:
        async with app.run_test() as pilot:
            await _wait_loaded(screen, pilot)
            await pilot.press("space")  # remove highlighted FIFA
            await pilot.press("/")
            await pilot.press(*list("naruto"))
            await pilot.pause()
            screen.query_one("#wantlist-table").focus()
            await pilot.press("space")  # include the sole Naruto match
            await pilot.press("enter")
            await pilot.pause()

            assert app.overrides["psp"].include == [
                "Ben 10",
                "Naruto Shippuden - Kizuna Drive",
            ]
            confirm = DownloadConfirmScreen(
                console_entry={"shortname": "psp", "class": "B"},
                override=app.overrides["psp"],
            )
            await app.push_screen(confirm)
            for _ in range(50):
                if confirm._loaded:
                    break
                await pilot.pause(0.05)
            assert confirm._wantlist == [
                "Ben 10",
                "Naruto Shippuden - Kizuna Drive",
            ]

    asyncio.run(run())
    assert not Path("overrides.yml").exists()
