"""Pilot: open CoverageScreen; wait for @work compute; assert table populated; export."""
from __future__ import annotations
import asyncio, pathlib, tempfile

from retrofetch.config import load_config, _yaml_rt
from retrofetch.tui.app import RetrofetchApp
from retrofetch.tui.screens.coverage import CoverageScreen


async def main() -> None:
    config = load_config(pathlib.Path("config.yml.example"))
    consoles = _yaml_rt.load(pathlib.Path("consoles.yml").read_text(encoding="utf-8"))

    with tempfile.TemporaryDirectory() as td:
        td_path = pathlib.Path(td)
        config.roms_root = td_path / "ROMs"
        config.roms_root.mkdir(parents=True)
        app = RetrofetchApp(
            config=config,
            config_path=pathlib.Path("config.yml.example"),
            consoles_yml=consoles,
            overrides={},
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = CoverageScreen()
            await app.push_screen(screen)
            await pilot.pause(5.0)

            table = screen.query_one("#coverage-table")
            assert table.row_count == 178, f"expected 178 rows, got {table.row_count}"

            # Export
            import os
            cwd = os.getcwd()
            os.chdir(td)
            try:
                await pilot.press("e")
                await pilot.pause(0.5)
                out = td_path / "coverage.md"
                assert out.exists(), "coverage.md not written"
                assert "# retrofetch Coverage Report" in out.read_text(encoding="utf-8")
            finally:
                os.chdir(cwd)

    print("T20 coverage: OK (178 rows, export OK)")


asyncio.run(main())
