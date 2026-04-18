"""Pilot: open ConfigEditor, change default_limit, ctrl+s, verify saved."""
from __future__ import annotations
import asyncio, pathlib, shutil, tempfile

from retrofetch.config import load_config, _yaml_rt
from retrofetch.tui.app import RetrofetchApp
from retrofetch.tui.screens.config_editor import ConfigEditorScreen


async def main() -> None:
    with tempfile.TemporaryDirectory() as td:
        td_path = pathlib.Path(td)
        cfg_path = td_path / "config.yml"
        shutil.copyfile(".sisyphus/fixtures/commented-config.yml", cfg_path)

        # Load a functional config for app construction (not the fixture — it lacks roms_root)
        config = load_config(pathlib.Path("config.yml.example"))
        consoles = _yaml_rt.load(pathlib.Path("consoles.yml").read_text(encoding="utf-8"))
        app = RetrofetchApp(
            config=config,
            config_path=cfg_path,
            consoles_yml=consoles,
            overrides={},
        )

        async with app.run_test() as pilot:
            await pilot.pause()
            screen = ConfigEditorScreen(config_path=cfg_path)
            await app.push_screen(screen)
            await pilot.pause(0.5)

            dl_input = screen.query_one("#cfg-default_limit")
            dl_input.value = "50"
            await pilot.pause()
            await pilot.press("ctrl+s")
            await pilot.pause(0.5)

            saved_text = cfg_path.read_text(encoding="utf-8")
            assert "default_limit: 50" in saved_text, f"default_limit: 50 not in saved file: {saved_text[:300]}"
            # Comments preserved
            assert "# retrofetch" in saved_text, "comment header lost"
    print("T21 config-save: OK (default_limit=50, comments preserved)")


asyncio.run(main())
