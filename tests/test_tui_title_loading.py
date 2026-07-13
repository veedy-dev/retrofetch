from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from textual.app import App, ComposeResult

from retrofetch.config import Config
from retrofetch.tui.messages import WantlistFailed, WantlistReady
from retrofetch.tui.screens import home as home_module
from retrofetch.tui.screens.home import HomeScreen
from retrofetch.tui.widgets.wantlist_preview import WantlistPreview


class _PreviewApp(App[None]):
    def compose(self) -> ComposeResult:
        yield WantlistPreview(id="preview")


class _HomeApp(App[None]):
    def __init__(self, screen: HomeScreen) -> None:
        super().__init__()
        self._home = screen
        self.config = Config(roms_root=Path("ROMs"), bios_root=Path("BIOS"))
        self.consoles_yml = {"consoles": []}
        self.overrides = {}

    async def on_mount(self) -> None:
        await self.push_screen(self._home)


def test_home_fetch_requests_the_complete_catalog(monkeypatch) -> None:
    titles = [f"Game {index:04d}" for index in range(1001)]
    captured: dict[str, object] = {}

    def fake_get_or_fetch_wantlist(**kwargs):
        captured.update(kwargs)
        return titles, False

    monkeypatch.setattr(
        home_module, "get_or_fetch_wantlist", fake_get_or_fetch_wantlist
    )
    messages = []
    fake_screen = SimpleNamespace(
        app=SimpleNamespace(overrides={}, config=Config(roms_root=Path("ROMs"))),
        post_message=messages.append,
    )

    cast(Any, HomeScreen._kick_preview_fetch).__wrapped__(
        fake_screen,
        {"shortname": "psx", "class": "B"},
        7,
    )

    assert captured["limit"] == 0
    assert len(messages) == 1
    assert isinstance(messages[0], WantlistReady)
    assert messages[0].titles == titles
    assert messages[0].request_id == 7


def test_preview_uses_native_loading_and_hides_cache_provenance() -> None:
    async def run() -> None:
        app = _PreviewApp()
        async with app.run_test():
            preview = app.query_one("#preview", WantlistPreview)

            preview.show_loading("psx")
            assert preview.state == "LOADING"
            assert preview.loading is True

            preview.show_ready("psx", [f"Game {index}" for index in range(1001)], {})
            ready_text = str(preview.render())
            assert preview.state == "READY"
            assert preview.loading is False
            assert ready_text.startswith("psx - 1001 titles\n")
            assert "Page 1/51" in ready_text
            assert "fresh" not in ready_text.casefold()
            assert "cached" not in ready_text.casefold()

            preview.show_loading("psx")
            preview.show_failed("psx", "offline")
            assert preview.state == "FAILED"
            assert preview.loading is False

            preview.show_loading("psx")
            preview.show_idle()
            assert preview.state == "IDLE"
            assert preview.loading is False

    asyncio.run(run())


def test_late_results_cannot_overwrite_unsupported_idle_selection() -> None:
    screen = HomeScreen()
    app = _HomeApp(screen)

    async def run() -> None:
        async with app.run_test():
            preview = screen.query_one("#main-panel", WantlistPreview)
            screen._last_highlighted = None
            screen._preview_generation = 4
            preview.show_idle()
            idle_text = str(preview.render())

            screen.on_wantlist_ready(
                WantlistReady("psx", ["Late Game"], False, request_id=4)
            )
            screen.on_wantlist_failed(
                WantlistFailed("psx", "late failure", request_id=4)
            )

            assert preview.state == "IDLE"
            assert preview.loading is False
            assert str(preview.render()) == idle_text

    asyncio.run(run())


def test_only_current_request_can_update_the_same_console() -> None:
    screen = HomeScreen()
    app = _HomeApp(screen)

    async def run() -> None:
        async with app.run_test():
            preview = screen.query_one("#main-panel", WantlistPreview)
            screen._last_highlighted = "psx"
            screen._preview_generation = 8
            preview.show_loading("psx")

            screen.on_wantlist_ready(
                WantlistReady("psx", ["Stale Game"], False, request_id=7)
            )
            screen.on_wantlist_failed(
                WantlistFailed("psx", "stale failure", request_id=7)
            )
            screen.on_wantlist_ready(
                WantlistReady("psp", ["Wrong Console"], False, request_id=8)
            )
            assert preview.state == "LOADING"
            assert preview.loading is True

            screen.on_wantlist_ready(
                WantlistReady("psx", ["Current Game"], False, request_id=8)
            )
            assert preview.state == "READY"
            assert preview.loading is False
            assert "Current Game" in str(preview.render())

    asyncio.run(run())
