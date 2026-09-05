from __future__ import annotations

import asyncio
import threading
from pathlib import Path

from textual.app import ComposeResult
from textual.coordinate import Coordinate
from textual.events import Mount
from textual.screen import Screen
from textual.widgets import DataTable, Label

from retrofetch.config import Config, ConsoleOverride
from retrofetch.tui.app import RetrofetchApp
from retrofetch.tui.screens.download_confirm import DownloadConfirmScreen
from retrofetch.tui.screens.wantlist import WantlistScreen


class _HomeScreen(Screen[None]):
    def compose(self) -> ComposeResult:
        yield Label("home", id="home-label")


class _WantlistApp(RetrofetchApp):
    CSS_PATH = "../retrofetch/tui/styles.tcss"

    def __init__(self, screen: WantlistScreen) -> None:
        super().__init__(
            config=Config(roms_root=Path("ROMs"), cache_dir=Path(".cache")),
            config_path=Path("config.yml"),
            consoles_yml={"consoles": []},
            overrides={},
        )
        self.screen_to_push = screen

    def on_mount(self, event: Mount | None = None) -> None:
        if event is not None:
            event.prevent_default()
        self.push_screen(_HomeScreen())
        self.push_screen(self.screen_to_push)


async def _wait_loaded(screen: WantlistScreen, pilot) -> None:
    for _ in range(50):
        if screen._loaded:
            return
        await pilot.pause(0.05)
    raise AssertionError("wantlist did not load")


def test_space_updates_session_and_enter_reviews_queue(
    monkeypatch, scratch_path
) -> None:
    monkeypatch.chdir(scratch_path)
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
            assert isinstance(app.screen, DownloadConfirmScreen)
            assert app.overrides["psp"].include == ["Burnout Dominator"]

    asyncio.run(run())
    assert not Path("overrides.yml").exists()


def test_queued_filter_and_back_keep_session_selection(
    monkeypatch, scratch_path
) -> None:
    monkeypatch.chdir(scratch_path)
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
            assert app.overrides["psp"].include == ["Burnout Dominator"]
            assert screen.query_one("#wantlist-table", DataTable).row_count == 1
            await pilot.press("escape")
            await pilot.pause()
            assert isinstance(app.screen, _HomeScreen)
            assert app.overrides["psp"].include == ["Burnout Dominator"]

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
            assert screen.query_one("#wantlist-table", DataTable).row_count == 100
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


def test_refresh_during_load_does_not_start_another_fetch(
    monkeypatch, scratch_path
) -> None:
    monkeypatch.chdir(scratch_path)
    started = threading.Event()
    release = threading.Event()
    calls = 0

    def fetch(**_kwargs):
        nonlocal calls
        calls += 1
        started.set()
        assert release.wait(2)
        return ["Game"], False

    monkeypatch.setattr("retrofetch.tui.screens.wantlist.get_or_fetch_wantlist", fetch)
    screen = WantlistScreen(
        console_entry={"shortname": "snes", "class": "A"},
        override=ConsoleOverride(),
    )
    app = _WantlistApp(screen)

    async def run() -> None:
        async with app.run_test() as pilot:
            for _ in range(50):
                if started.is_set():
                    break
                await pilot.pause(0.01)
            assert started.is_set()
            screen.action_refresh()
            screen.action_refresh()
            assert calls == 1
            release.set()
            await _wait_loaded(screen, pilot)

    asyncio.run(run())


def test_selection_updates_runtime_queue(monkeypatch, scratch_path) -> None:
    monkeypatch.chdir(scratch_path)
    titles = ["FIFA", "Ben 10", "Naruto Shippuden - Kizuna Drive"]
    monkeypatch.setattr(
        "retrofetch.tui.screens.wantlist.get_or_fetch_wantlist",
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
            confirm = app.screen
            assert isinstance(confirm, DownloadConfirmScreen)
            assert confirm._wantlist == [
                "Ben 10",
                "Naruto Shippuden - Kizuna Drive",
            ]

    asyncio.run(run())
    assert not Path("overrides.yml").exists()


def test_search_focus_bulk_queue_and_background_removal(
    monkeypatch, scratch_path
) -> None:
    monkeypatch.chdir(scratch_path)
    titles = ["Quest [USA]", "Quest Two", "Other"]
    monkeypatch.setattr(
        "retrofetch.tui.screens.wantlist.get_or_fetch_wantlist",
        lambda **kwargs: (titles, True),
    )
    screen = WantlistScreen(
        console_entry={"shortname": "psp", "class": "B"}, override=None
    )
    app = _WantlistApp(screen)
    app.overrides["other"] = ConsoleOverride(
        include=["Keep"], region_priority=["Europe"]
    )

    async def run() -> None:
        async with app.run_test() as pilot:
            await _wait_loaded(screen, pilot)
            await pilot.press("/", *list("quest"))
            from textual.widgets import Input

            assert screen.query_one(Input).value == "quest"
            assert app.screen is screen
            await pilot.press("enter")
            table = screen.query_one(DataTable)
            assert table.has_focus
            assert str(table.get_cell_at(Coordinate(0, 1))) == "Quest [USA]"
            await pilot.press("ctrl+a")
            assert set(app.overrides["psp"].include) == set(titles[:2])
            app.update_selection("psp", ["Quest Two"], [])
            await pilot.pause()
            await pilot.press("down", "space")
            assert app.overrides["psp"].include == []
            assert app.overrides["other"].include == ["Keep"]
            await pilot.press("/", "escape")
            assert table.has_focus
            await pilot.press("escape")
            assert isinstance(app.screen, _HomeScreen)

    asyncio.run(run())


def test_background_failure_updates_browser_without_losing_cursor(
    monkeypatch, scratch_path
) -> None:
    from retrofetch.tui.downloads import DownloadSession
    from retrofetch.tui.messages import GameFailed, GameStart

    monkeypatch.chdir(scratch_path)
    monkeypatch.setattr(
        "retrofetch.tui.screens.wantlist.get_or_fetch_wantlist",
        lambda **kwargs: (["First", "Second"], True),
    )
    entry = {"shortname": "psp", "class": "B"}
    screen = WantlistScreen(console_entry=entry, override=None)
    app = _WantlistApp(screen)

    async def run() -> None:
        async with app.run_test() as pilot:
            await _wait_loaded(screen, pilot)
            await pilot.press("down")
            table = screen.query_one(DataTable)
            app.download_session = DownloadSession(entry, ["First"])
            app.download_session.apply(
                GameStart("First", "archive_org", "psp", "first-id")
            )
            await pilot.pause(0.3)
            app.download_session.apply(GameFailed("First", "offline", "first-id"))
            await pilot.pause(0.3)
            assert str(table.get_cell_at(Coordinate(0, 2))) == "Failed"
            assert str(table.get_cell_at(Coordinate(table.cursor_row, 1))) == "Second"
            assert table.has_focus

    asyncio.run(run())


def test_narrow_browser_keeps_status_and_full_title_accessible(
    monkeypatch, scratch_path
) -> None:
    from retrofetch.tui.downloads import DownloadSession
    from retrofetch.tui.messages import GameStage

    monkeypatch.chdir(scratch_path)
    title = "An exceptionally long game title [USA] with a complete release and edition name"
    monkeypatch.setattr(
        "retrofetch.tui.screens.wantlist.get_or_fetch_wantlist",
        lambda **kwargs: (
            ["First", title] + [f"Game {index}" for index in range(30)],
            True,
        ),
    )
    entry = {"shortname": "psp", "class": "B"}
    screen = WantlistScreen(console_entry=entry, override=None)
    app = _WantlistApp(screen)
    app.download_session = DownloadSession(entry, [title])
    app.download_session.apply(GameStage(title, "Downloading", item_id="long-title"))

    async def run() -> None:
        async with app.run_test(size=(120, 30)) as pilot:
            await _wait_loaded(screen, pilot)
            await pilot.pause()
            table = screen.query_one(DataTable)
            assert table.max_scroll_x == 0
            await pilot.press("down")
            await pilot.resize_terminal(80, 24)
            await pilot.pause()
            detail = screen.query_one("#game-detail", Label)
            assert table.max_scroll_x == 0
            assert "Downloading" in str(table.get_cell_at(Coordinate(1, 2)))
            assert table.cursor_row == 1
            assert table.has_focus
            assert str(detail.render()) == title
            assert detail.region.right <= screen.region.right
            assert detail.region.bottom <= screen.region.bottom

    asyncio.run(run())
