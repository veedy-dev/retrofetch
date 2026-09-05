from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from textual.coordinate import Coordinate
from textual.events import Mount
from textual.widgets import DataTable, Input, Label, ListItem, ListView, OptionList

from retrofetch.config import Config, ConsoleOverride
from retrofetch.sources.bios import BiosFile
from retrofetch.tui.app import RetrofetchApp
from retrofetch.tui.screens.bios import BiosScreen
from retrofetch.tui.screens.download_confirm import DownloadConfirmScreen
from retrofetch.tui.screens.home import HomeScreen
from retrofetch.tui.screens.wantlist import WantlistScreen
from retrofetch.tui.widgets.wantlist_preview import WantlistPreview
from retrofetch.wantlist_cache import is_recently_empty, mark_empty


class _TuiApp(RetrofetchApp):
    CSS_PATH = "../retrofetch/tui/styles.tcss"

    def __init__(self, screen) -> None:
        overrides = {}
        if isinstance(screen, DownloadConfirmScreen) and screen.override is not None:
            overrides[screen.shortname] = screen.override
        super().__init__(
            config=Config(roms_root=Path("ROMs"), bios_root=Path("BIOS")),
            config_path=Path("config.yml"),
            consoles_yml={"consoles": []},
            overrides=overrides,
        )
        self.screen_to_push = screen

    def on_mount(self, event: Mount | None = None) -> None:
        if event is not None:
            event.prevent_default()
        self.push_screen(self.screen_to_push)


def test_home_availability_accepts_minerva_only_source() -> None:
    assert HomeScreen._is_available(
        {"shortname": "minervaonly", "class": "A", "minerva_path": "No-Intro/Test"}
    )


def test_empty_fetch_marker_does_not_disable_browse_provider(scratch_path) -> None:
    mark_empty(scratch_path, "psp")

    assert is_recently_empty(scratch_path, "psp")
    assert HomeScreen._is_available(
        {"shortname": "psp", "class": "B", "minerva_path": "Redump/PSP"}
    )


def test_console_search_shortcut_filters_without_inserting_slash() -> None:
    screen = HomeScreen()
    app = _TuiApp(screen)
    app.consoles_yml = {
        "consoles": [
            {
                "shortname": "gb",
                "display_name": "Nintendo Game Boy",
                "class": "E",
            },
            {
                "shortname": "psp",
                "display_name": "Sony PlayStation Portable",
                "class": "E",
            },
            {
                "shortname": "nes",
                "display_name": "Nintendo Entertainment System",
                "class": "E",
            },
        ]
    }

    async def run() -> None:
        async with app.run_test() as pilot:
            console_list = screen.query_one(ListView)
            console_list.index = 1
            await pilot.press("/")
            await pilot.press(*list("Nintendo"))
            await pilot.pause(0.3)

            assert screen.query_one("#filter", Input).value == "Nintendo"
            visible_items = [
                item for item in console_list.query(ListItem) if item.display
            ]
            assert [str(item.query_one(Label).content) for item in visible_items] == [
                "[E] Nintendo Game Boy",
                "[E] Nintendo Entertainment System",
            ]
            assert console_list.highlighted_child is visible_items[0]
            await pilot.press("enter")
            assert console_list.has_focus

    asyncio.run(run())


def test_download_confirm_removes_game_from_shared_queue() -> None:
    override = ConsoleOverride(include=["A", "B", "C"])
    screen = DownloadConfirmScreen(
        console_entry={"shortname": "nes", "class": "A"},
        override=override,
    )
    app = _TuiApp(screen)

    async def run() -> None:
        async with app.run_test() as pilot:
            for _ in range(50):
                if screen._loaded:
                    break
                await pilot.pause(0.05)
            options = screen.query_one("#wantlist-preview", OptionList)
            assert options.highlighted == 0
            await pilot.press("x")
            await pilot.pause()
            await pilot.press("delete")
            await pilot.pause()
            assert screen._wantlist == ["C"]
            assert options.option_count == 1
            assert app.overrides["nes"].include == ["C"]
            reopened = DownloadConfirmScreen(
                console_entry=screen.console_entry, override=override
            )
            await app.push_screen(reopened)
            await pilot.pause()
            assert reopened._wantlist == ["C"]

    asyncio.run(run())


def test_empty_queue_cannot_start() -> None:
    screen = DownloadConfirmScreen(
        console_entry={"shortname": "nes", "class": "A"},
        override=ConsoleOverride(),
    )
    app = _TuiApp(screen)

    async def run() -> None:
        async with app.run_test() as pilot:
            await pilot.press("enter")
            assert app.screen is screen
            assert app.download_session is None

    asyncio.run(run())


def test_bios_screen_lists_and_downloads(monkeypatch, scratch_path) -> None:
    class _FakeBiosSource:
        def list_files(self, console: str):
            return SimpleNamespace(
                files=[
                    BiosFile(
                        console,
                        "scph5501.bin",
                        "https://example/scph5501.bin",
                        10,
                        "archive_org",
                    )
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
    app.config = Config(
        roms_root=scratch_path / "ROMs", bios_root=scratch_path / "BIOS"
    )

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
            assert (
                scratch_path / "BIOS" / "psx" / "scph5501.bin"
            ).read_bytes() == b"bios"

    asyncio.run(run())


def test_bios_download_failure_allows_manual_retry(monkeypatch, scratch_path, caplog):
    attempts = 0
    secret = "synthetic-private-bios-token"

    def list_files(self, console):
        return SimpleNamespace(
            files=[BiosFile(console, "fixture.bin", "https://example.test/fixture", 1, "fixture")]
        )

    def download(self, console, root):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError(secret)
        return [root / console / "fixture.bin"]

    monkeypatch.setattr("retrofetch.tui.screens.bios.BiosSource.list_files", list_files)
    monkeypatch.setattr("retrofetch.tui.screens.bios.BiosSource.download", download)
    screen = BiosScreen(console_entry={"shortname": "fixture", "class": "B"})
    app = _TuiApp(screen)
    app.config = Config(roms_root=scratch_path / "ROMs", bios_root=scratch_path / "BIOS")

    async def run():
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert attempts == 1
            assert "RuntimeError" in caplog.text
            assert secret not in caplog.text
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert attempts == 2
            assert str(app.config.bios_root / "fixture") in str(
                screen.query_one("#bios-summary", Label).content
            )

    asyncio.run(run())


@pytest.mark.parametrize("view", ["home", "wantlist"])
def test_refresh_reports_symlink_loop_and_recovers(monkeypatch, scratch_path, view):
    loop = scratch_path / "cache-loop"
    try:
        loop.symlink_to(loop, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {type(exc).__name__}")
    monkeypatch.setattr(
        "retrofetch.ranker.get_wantlist", lambda *args, **kwargs: ["Fixture game"]
    )
    entry = {"shortname": "fixture", "class": "A", "minerva_path": "fixture"}
    screen = (
        HomeScreen()
        if view == "home"
        else WantlistScreen(console_entry=entry, override=None)
    )
    app = _TuiApp(screen)
    app.consoles_yml = {"consoles": [entry]}
    cache_dir = scratch_path / "cache"
    app.config = Config(roms_root=scratch_path / "ROMs", cache_dir=cache_dir)
    refresh_key = "ctrl+r" if view == "home" else "r"

    async def run():
        async with app.run_test() as pilot:
            if view == "home":
                screen.query_one(ListView).focus()
                screen.query_one(ListView).index = 0
            await pilot.pause(0.4)
            await app.workers.wait_for_complete()
            await pilot.pause()
            app.config.cache_dir = loop
            await pilot.press(refresh_key)
            await app.workers.wait_for_complete()
            await pilot.pause()
            if view == "home":
                assert screen.query_one(WantlistPreview).state == "FAILED"
            else:
                assert str(loop) in str(screen.query_one("#status-line", Label).content)
                assert screen.query_one(DataTable).row_count == 0
            app.config.cache_dir = cache_dir
            await pilot.press(refresh_key)
            await app.workers.wait_for_complete()
            await pilot.pause()
            if view == "home":
                assert screen.query_one(WantlistPreview).state == "READY"
            else:
                table = screen.query_one(DataTable)
                assert str(table.get_cell_at(Coordinate(0, 1))) == "Fixture game"

    asyncio.run(run())
