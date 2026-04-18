"""Pilot: press ?, assert help visible; press esc, assert dismissed."""
from __future__ import annotations
import asyncio, pathlib

from retrofetch.config import load_config, _yaml_rt
from retrofetch.tui.app import RetrofetchApp
from retrofetch.tui.screens.help import HelpScreen


async def main() -> None:
    config = load_config(pathlib.Path("config.yml.example"))
    consoles = _yaml_rt.load(pathlib.Path("consoles.yml").read_text(encoding="utf-8"))
    app = RetrofetchApp(
        config=config,
        config_path=pathlib.Path("config.yml.example"),
        consoles_yml=consoles,
        overrides={},
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.push_screen(HelpScreen())
        await pilot.pause(0.3)
        assert list(app.screen.query("Label#help-title")), "help title not visible"
        await pilot.press("escape")
        await pilot.pause(0.3)
        # Help screen should be dismissed
        assert not any(isinstance(s, HelpScreen) for s in app.screen_stack), "help not dismissed"
    print("T22 help: OK (modal open + dismiss)")


asyncio.run(main())
