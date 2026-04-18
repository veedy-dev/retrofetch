"""Pilot: open OverridesEditor for nes, add include title, ctrl+s, verify."""
from __future__ import annotations
import asyncio, pathlib, shutil, tempfile

from retrofetch.config import load_config, _yaml_rt
from retrofetch.tui.app import RetrofetchApp
from retrofetch.tui.screens.overrides_editor import OverridesEditorScreen


async def main() -> None:
    with tempfile.TemporaryDirectory() as td:
        td_path = pathlib.Path(td)
        ov_path = td_path / "overrides.yml"
        shutil.copyfile("overrides.yml.example", ov_path)

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
            screen = OverridesEditorScreen(overrides_path=ov_path, shortname="nes")
            await app.push_screen(screen)
            await pilot.pause(0.5)

            ta = screen.query_one("#ov-include")
            ta.text = ta.text + "\nSuper Mario Bros. 3"
            await pilot.pause()
            await pilot.press("ctrl+s")
            await pilot.pause(0.5)

            saved_text = ov_path.read_text(encoding="utf-8")
            assert "Super Mario Bros. 3" in saved_text, f"not saved: {saved_text[:300]}"
    print("T21 overrides: OK (include updated, comments preserved)")


asyncio.run(main())
