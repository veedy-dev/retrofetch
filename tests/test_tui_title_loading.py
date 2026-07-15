from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from textual.app import App, ComposeResult
from textual.widget import Widget
from textual.widgets import ListItem, ListView

from retrofetch.config import Config, ConsoleOverride
from retrofetch.tui.messages import WantlistFailed, WantlistReady
from retrofetch.tui.screens import home as home_module
from retrofetch.tui.screens.home import HomeScreen
from retrofetch.tui.screens.wantlist import WantlistScreen
from retrofetch.tui.widgets.wantlist_preview import WantlistPreview
from retrofetch.wantlist_cache import load_cached


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


def test_explicit_home_refresh_requests_the_complete_catalog(monkeypatch) -> None:
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


def test_home_cache_miss_automatically_loads_catalog(monkeypatch, scratch_path) -> None:
    calls = 0

    def fetch(**_kwargs):
        nonlocal calls
        calls += 1
        return ["Auto Game"], False

    monkeypatch.setattr(home_module, "get_or_fetch_wantlist", fetch)
    screen = HomeScreen()
    app = _HomeApp(screen)
    app.config = Config(
        roms_root=scratch_path / "ROMs", cache_dir=scratch_path / ".cache"
    )
    app.consoles_yml = {
        "consoles": [
            {
                "shortname": "ps2",
                "display_name": "Sony PlayStation 2",
                "class": "B",
                "minerva_path": "Redump/Sony - PlayStation 2",
            }
        ]
    }

    async def run() -> None:
        async with app.run_test() as pilot:
            screen.query_one("#console-list", ListView).index = 0
            await pilot.pause()
            preview = screen.query_one("#main-panel", WantlistPreview)
            assert preview.state == "LOADING"
            for _ in range(100):
                if preview.state == "READY":
                    break
                await pilot.pause(0.01)
            assert preview.state == "READY"
            assert "Auto Game" in str(preview.render())

    asyncio.run(run())
    assert calls == 1


def test_rapid_highlight_before_debounce_only_starts_latest_console(
    monkeypatch, scratch_path
) -> None:
    entries = [
        {"shortname": "psp", "class": "B", "minerva_path": "Redump/PSP"},
        {"shortname": "ps2", "class": "B", "minerva_path": "Redump/PS2"},
    ]
    calls: list[tuple[str, int]] = []
    started = threading.Event()
    screen = HomeScreen()
    monkeypatch.setattr(screen, "_PREVIEW_DEBOUNCE_MS", 1)
    app = _HomeApp(screen)
    app.config = Config(
        roms_root=scratch_path / "ROMs", cache_dir=scratch_path / ".cache"
    )
    app.consoles_yml = {"consoles": entries}

    async def run() -> None:
        async with app.run_test() as pilot:
            def record_fetch(entry, request_id) -> None:
                calls.append((str(entry["shortname"]), request_id))
                started.set()

            monkeypatch.setattr(
                screen,
                "_kick_preview_fetch",
                record_fetch,
            )
            list_view = screen.query_one("#console-list", ListView)
            first = cast(ListItem, list_view.children[0])
            second = cast(ListItem, list_view.children[1])

            screen.on_list_view_highlighted(ListView.Highlighted(list_view, first))
            screen.on_list_view_highlighted(ListView.Highlighted(list_view, second))
            for _ in range(100):
                if started.is_set():
                    break
                await pilot.pause(0.01)
            assert started.is_set()
            await pilot.pause()

    asyncio.run(run())
    assert [shortname for shortname, _request_id in calls] == ["ps2"]
    assert set(screen._preview_fetching) == {"ps2"}


def test_overlapping_console_workers_accept_revisited_console_only(
    monkeypatch, scratch_path
) -> None:
    entries = [
        {"shortname": "psp", "class": "B", "minerva_path": "Redump/PSP"},
        {"shortname": "ps2", "class": "B", "minerva_path": "Redump/PS2"},
    ]
    psp_started = threading.Event()
    ps2_started = threading.Event()
    psp_revisited = threading.Event()
    release_psp = threading.Event()
    release_ps2 = threading.Event()

    def fetch(**kwargs):
        shortname = str(kwargs["console_entry"]["shortname"])
        if shortname == "psp":
            psp_started.set()
            assert release_psp.wait(5)
            return ["PSP Game"], False
        ps2_started.set()
        assert release_ps2.wait(5)
        return ["PS2 Game"], False

    monkeypatch.setattr(home_module, "get_or_fetch_wantlist", fetch)
    screen = HomeScreen()
    monkeypatch.setattr(screen, "_PREVIEW_DEBOUNCE_MS", 1)
    app = _HomeApp(screen)
    app.config = Config(
        roms_root=scratch_path / "ROMs", cache_dir=scratch_path / ".cache"
    )
    app.consoles_yml = {"consoles": entries}

    async def run() -> None:
        async with app.run_test() as pilot:
            list_view = screen.query_one("#console-list", ListView)
            psp_item = cast(ListItem, list_view.children[0])
            ps2_item = cast(ListItem, list_view.children[1])
            start_attempts: list[str] = []
            start_fetch = screen._start_preview_fetch

            def observe_start(entry, request_id) -> None:
                shortname = str(entry["shortname"])
                start_attempts.append(shortname)
                if start_attempts.count("psp") == 2:
                    psp_revisited.set()
                start_fetch(entry, request_id)

            monkeypatch.setattr(screen, "_start_preview_fetch", observe_start)

            async def wait_for(event: threading.Event) -> None:
                for _ in range(200):
                    if event.is_set():
                        return
                    await pilot.pause(0.01)
                raise AssertionError("worker event was not observed")

            try:
                screen.on_list_view_highlighted(
                    ListView.Highlighted(list_view, psp_item)
                )
                await wait_for(psp_started)
                psp_token = screen._preview_fetching["psp"]

                screen.on_list_view_highlighted(
                    ListView.Highlighted(list_view, ps2_item)
                )
                await wait_for(ps2_started)
                ps2_token = screen._preview_fetching["ps2"]
                assert not release_psp.is_set()

                screen.on_list_view_highlighted(
                    ListView.Highlighted(list_view, psp_item)
                )
                await wait_for(psp_revisited)
                assert screen._preview_fetching == {
                    "psp": psp_token,
                    "ps2": ps2_token,
                }

                release_psp.set()
                preview = screen.query_one("#main-panel", WantlistPreview)
                for _ in range(200):
                    if "psp" not in screen._preview_fetching:
                        break
                    await pilot.pause(0.01)
                assert preview.state == "READY"
                assert "PSP Game" in str(preview.render())

                release_ps2.set()
                for _ in range(200):
                    if "ps2" not in screen._preview_fetching:
                        break
                    await pilot.pause(0.01)
                assert not screen._preview_fetching
                assert "PSP Game" in str(preview.render())
                assert "PS2 Game" not in str(preview.render())
            finally:
                release_psp.set()
                release_ps2.set()

    asyncio.run(run())


def test_returning_from_select_games_refreshes_home_from_raw_cache(
    monkeypatch, scratch_path
) -> None:
    monkeypatch.setattr(
        "retrofetch.ranker.get_wantlist",
        lambda **_kwargs: ["Visible Game", "Hidden Game"],
    )
    screen = HomeScreen()
    app = _HomeApp(screen)
    app.config = Config(
        roms_root=scratch_path / "ROMs", cache_dir=scratch_path / ".cache"
    )
    app.consoles_yml = {
        "consoles": [
            {
                "shortname": "ps2",
                "display_name": "Sony PlayStation 2",
                "class": "B",
                "minerva_path": "Redump/Sony - PlayStation 2",
            }
        ]
    }
    app.overrides = {"ps2": ConsoleOverride(exclude=["Hidden Game"])}

    async def run() -> None:
        async with app.run_test() as pilot:
            screen.query_one("#console-list", ListView).index = 0
            await pilot.pause()
            screen.action_open_wantlist()
            for _ in range(100):
                current = app.screen
                if isinstance(current, WantlistScreen) and current._loaded:
                    break
                await pilot.pause(0.01)
            assert isinstance(app.screen, WantlistScreen)
            await pilot.press("enter")
            await pilot.pause()

            preview = screen.query_one("#main-panel", WantlistPreview)
            rendered = str(preview.render())
            assert "Visible Game" in rendered
            assert "Hidden Game" not in rendered

    asyncio.run(run())
    cached = load_cached(scratch_path / ".cache", "ps2")
    assert cached is not None
    assert cached.titles == ["Visible Game", "Hidden Game"]


def test_home_loading_indicator_fills_and_matches_main_panel() -> None:
    async def run() -> None:
        screen = HomeScreen()
        app = _HomeApp(screen)
        async with app.run_test(size=(111, 40)) as pilot:
            preview = screen.query_one("#main-panel", WantlistPreview)
            preview.show_loading("psx")
            await pilot.pause()

            loading = preview._cover_widget
            assert loading is not None
            parent = preview.parent
            assert isinstance(parent, Widget)
            assert loading.outer_size.height == parent.content_size.height
            assert loading.background_colors == preview.background_colors

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
            screen._preview_generation = 9
            screen._preview_fetching["psx"] = 8
            preview.show_loading("psx")

            screen.on_wantlist_ready(
                WantlistReady("psx", ["Stale Game"], False, request_id=7)
            )
            assert screen._preview_fetching == {"psx": 8}
            screen.on_wantlist_failed(
                WantlistFailed("psx", "stale failure", request_id=7)
            )
            assert screen._preview_fetching == {"psx": 8}
            screen.on_wantlist_ready(
                WantlistReady("psp", ["Wrong Console"], False, request_id=8)
            )
            assert screen._preview_fetching == {"psx": 8}
            assert preview.state == "LOADING"
            assert preview.loading is True

            screen.on_wantlist_ready(
                WantlistReady("psx", ["Current Game"], False, request_id=8)
            )
            assert "psx" not in screen._preview_fetching
            assert preview.state == "READY"
            assert preview.loading is False
            assert "Current Game" in str(preview.render())

    asyncio.run(run())
