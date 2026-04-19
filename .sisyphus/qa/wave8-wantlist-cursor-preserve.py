"""Regression: toggling include/exclude on a non-zero row must NOT reset cursor to 0.

Bug: `_render_page()` unconditionally set `cursor_coordinate = (0, 0)`, so
pressing space or x on row N jumped the cursor back to row 0. Fix: toggle
actions call `_update_current_row_cells()` instead, which uses
`DataTable.update_cell_at()` for in-place cell updates and preserves cursor.
"""
from __future__ import annotations

import asyncio
import pathlib
from unittest.mock import patch

from retrofetch.config import load_config, _yaml_rt
from retrofetch.tui.app import RetrofetchApp
from retrofetch.tui.screens.wantlist import WantlistScreen


async def main() -> None:
    config = load_config(pathlib.Path("config.yml.example"))
    consoles_yml = _yaml_rt.load(pathlib.Path("consoles.yml").read_text(encoding="utf-8"))
    entry = next(
        e for e in consoles_yml.get("consoles", []) if str(e.get("class")) == "A"
    )

    titles = [f"Title {i:02d}" for i in range(1, 21)]  # 20 rows

    app = RetrofetchApp(
        config=config,
        config_path=pathlib.Path("config.yml.example"),
        consoles_yml=consoles_yml,
        overrides={},
    )

    def fake_wantlist(**_kwargs):
        return titles, True

    async with app.run_test() as pilot:
        await pilot.pause()
        with patch(
            "retrofetch.tui.screens.wantlist.get_or_fetch_wantlist",
            side_effect=fake_wantlist,
        ):
            screen = WantlistScreen(console_entry=entry, override=None)
            await app.push_screen(screen)
            await pilot.pause()
            screen._wantlist = list(titles)
            screen._loaded_source = "cached"
            screen._page = 0
            screen._render_page()
            await pilot.pause()

            from textual.widgets import DataTable  # pyright: ignore[reportMissingImports]
            table: DataTable = screen.query_one("#wantlist-table", DataTable)

            # Move cursor to row 10 (a non-zero row).
            table.cursor_coordinate = table.cursor_coordinate.__class__(10, 0)
            await pilot.pause()
            assert table.cursor_row == 10, f"setup failed: cursor at {table.cursor_row}"

            # Toggle include on row 10 -> cursor MUST stay at 10.
            screen.action_toggle_include()
            await pilot.pause()
            assert table.cursor_row == 10, (
                f"BUG: cursor jumped from 10 to {table.cursor_row} after toggle_include"
            )
            assert titles[10] in screen._include, "toggle_include didn't add the title"

            # sel column for row 10 should now show '[x]'
            num_col = list(table.columns.keys())[0]
            sel_col = list(table.columns.keys())[1]
            inc_col = list(table.columns.keys())[4]
            row10_key = list(table.rows.keys())[10]
            sel_cell = table.get_cell(row10_key, sel_col)
            inc_cell = table.get_cell(row10_key, inc_col)
            sel_plain = sel_cell.plain if hasattr(sel_cell, "plain") else str(sel_cell)
            assert sel_plain == "[x]", f"row 10 sel should be '[x]', got {sel_plain!r}"
            assert inc_cell == "yes", f"row 10 Included should be 'yes', got {inc_cell!r}"

            # Toggle x on row 10 -> cursor STILL at 10, include cleared, exclude set.
            screen.action_toggle_exclude()
            await pilot.pause()
            assert table.cursor_row == 10, (
                f"BUG: cursor jumped from 10 to {table.cursor_row} after toggle_exclude"
            )
            assert titles[10] not in screen._include, "include not cleared on exclude toggle"
            assert titles[10] in screen._exclude, "exclude not set"
            sel_cell2 = table.get_cell(row10_key, sel_col)
            sel_plain2 = sel_cell2.plain if hasattr(sel_cell2, "plain") else str(sel_cell2)
            assert sel_plain2 == "[ ]", f"row 10 sel should be '[ ]' after exclude, got {sel_plain2!r}"

            # Verify row 0 content is completely untouched across both toggles.
            row0_key = list(table.rows.keys())[0]
            row0_num = table.get_cell(row0_key, num_col)
            assert row0_num == "1", f"row 0 number changed: {row0_num!r}"

        app.exit(0)

    print("wave8 cursor-preserve: OK (cursor stays on row 10 through include + exclude toggles)")


asyncio.run(main())
