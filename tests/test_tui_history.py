from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from types import SimpleNamespace

from textual.app import App
from textual.widgets import DataTable, Label

from retrofetch.state import GameAttempt, GameEntry, State, save_state, state_path
from retrofetch.tui.screens.state import StateScreen


class HistoryApp(App[None]):
    CSS_PATH = Path(__file__).parents[1] / "retrofetch/tui/styles.tcss"

    def __init__(self, root: Path) -> None:
        super().__init__()
        self.config = SimpleNamespace(roms_root=root)
        self.history = StateScreen(console_entry={"shortname": "test"})

    async def on_mount(self) -> None:
        await self.push_screen(self.history)


def test_history_distinguishes_downloads_and_verification_without_mutation(
    scratch_path,
):
    games = [
        GameEntry(
            "Twin [red]",
            "acquired",
            filename="Twin (USA).zip",
            item_id="usa",
            size_bytes=1024,
        ),
        GameEntry(
            "Twin [red]", "unverified", filename="Twin (Europe).zip", item_id="eu"
        ),
        GameEntry(
            "Broken",
            "failed",
            attempts=[
                GameAttempt(
                    "archive", "download_failed: connection reset", "2026-09-05"
                )
            ],
        ),
        GameEntry("Stopped", "cancelled"),
        GameEntry("Ignored", "skipped"),
        GameEntry("Working", "pending"),
    ]
    save_state(State(console="test", games=games), scratch_path)
    path = state_path("test", scratch_path)
    before = path.read_bytes()

    async def run():
        app = HistoryApp(scratch_path)
        async with app.run_test(size=(100, 35)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            table = app.history.query_one(DataTable)
            rows = [
                [str(cell) for cell in table.get_row_at(index)]
                for index in range(table.row_count)
            ]
            assert [row[1] for row in rows] == [
                "Downloaded",
                "Downloaded",
                "Failed",
                "Cancelled",
                "Skipped",
                "In progress",
            ]
            assert rows[0][0] == rows[1][0] == "Twin [red]"
            details = app.history.query_one("#history-details", Label)
            assert "Verified" in str(details.render())
            assert "Twin (USA).zip" in str(details.render())
            await pilot.press("down")
            assert "Not checked" in str(details.render())
            assert "Twin (Europe).zip" in str(details.render())
            assert "Item ID: eu" in str(details.render())
            await pilot.press("down")
            assert "connection reset" in str(details.render())
            assert "Not applicable" in str(details.render())
            await pilot.press("r")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert "connection reset" in str(details.render())
            await pilot.press("escape")
            assert app.screen is not app.history

    asyncio.run(run())
    assert path.read_bytes() == before


def test_history_load_does_not_block_back_navigation(monkeypatch, scratch_path):
    import retrofetch.tui.screens.state as history_module

    started = threading.Event()
    release = threading.Event()
    original = history_module.load_state

    def slow_load(console, root):
        started.set()
        assert release.wait(5), "UI did not remain responsive while reading history"
        return original(console, root)

    monkeypatch.setattr(history_module, "load_state", slow_load)

    async def run():
        app = HistoryApp(scratch_path)
        try:
            async with app.run_test() as pilot:
                assert await asyncio.to_thread(started.wait, 2)
                await pilot.press("escape")
                assert app.screen is not app.history
                release.set()
                await pilot.pause()
        finally:
            release.set()

    asyncio.run(run())


def test_history_refresh_failure_preserves_rows_and_can_retry(
    monkeypatch, scratch_path
):
    import retrofetch.tui.screens.state as history_module

    save_state(
        State(console="test", games=[GameEntry("Saved", "unverified")]), scratch_path
    )
    original = history_module.load_state

    def denied(*_args):
        raise PermissionError("history permission denied")

    async def run():
        app = HistoryApp(scratch_path)
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            monkeypatch.setattr(history_module, "load_state", denied)
            await pilot.press("r")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert "permission denied" in str(
                app.history.query_one("#st-summary", Label).render()
            )
            assert str(app.history.query_one(DataTable).get_row_at(0)[0]) == "Saved"
            monkeypatch.setattr(history_module, "load_state", original)
            save_state(State(console="test"), scratch_path)
            await pilot.press("r")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.history.query_one(DataTable).row_count == 0
            assert "permission denied" not in str(
                app.history.query_one("#st-summary", Label).render()
            )
            assert str(app.history.query_one("#history-details", Label).render()) == ""

    asyncio.run(run())


def test_history_explains_existing_corrupt_file_recovery(scratch_path):
    path = state_path("test", scratch_path)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"not JSON")

    async def run():
        app = HistoryApp(scratch_path)
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert ".corrupt" in str(
                app.history.query_one("#st-summary", Label).render()
            )
            assert app.history.query_one(DataTable).row_count == 0

    asyncio.run(run())
    backups = list(path.parent.glob(".retrofetch-state.json.corrupt.*"))
    assert [backup.read_bytes() for backup in backups] == [b"not JSON"]


def test_history_long_items_fit_compact_table_and_keep_selected_details(scratch_path):
    title = "The Legend of a Very Long Game Name (Europe) (En,Fr,De,Es,It) [Rev 2]"
    provider = "archive.org / European preservation collection"
    filename = title + ".zip"
    games = [
        GameEntry("Earlier item", "acquired", item_id="first"),
        GameEntry(
            title,
            "unverified",
            filename=filename,
            item_id="second",
            provider=provider,
            size_bytes=1024,
        ),
    ]
    save_state(State(console="test", games=games), scratch_path)
    path = state_path("test", scratch_path)
    before = path.read_bytes()

    async def run():
        app = HistoryApp(scratch_path)
        async with app.run_test(size=(120, 35)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            await pilot.press("down")
            await pilot.resize_terminal(80, 24)
            await pilot.pause()
            table = app.history.query_one(DataTable)
            details = str(app.history.query_one("#history-details", Label).render())
            assert table.virtual_size.width <= table.scrollable_content_region.width
            assert table.scroll_x == 0
            assert str(table.get_row_at(table.cursor_row)[1]) == "Downloaded"
            assert str(table.get_row_at(table.cursor_row)[2]) == "1.0 KB"
            assert title in details and filename in details and provider in details
            assert "Item ID: second" in details
            await pilot.resize_terminal(100, 30)
            await pilot.pause()
            assert "Item ID: second" in str(
                app.history.query_one("#history-details", Label).render()
            )
            assert table.virtual_size.width <= table.scrollable_content_region.width

    asyncio.run(run())
    assert path.read_bytes() == before
