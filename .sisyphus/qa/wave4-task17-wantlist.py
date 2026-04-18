"""Pilot scenario: open wantlist, toggle include/exclude, save, verify overrides.yml."""
from __future__ import annotations
import asyncio, pathlib, shutil, tempfile

from retrofetch.config import load_config, load_overrides, _yaml_rt
from retrofetch.tui.app import RetrofetchApp
from retrofetch.tui.screens.wantlist import WantlistScreen


async def main() -> None:
    config = load_config(pathlib.Path("config.yml.example"))
    consoles = _yaml_rt.load(pathlib.Path("consoles.yml").read_text(encoding="utf-8"))
    entry = next(c for c in consoles["consoles"] if c["shortname"] == "nes")

    with tempfile.TemporaryDirectory() as td:
        td_path = pathlib.Path(td)
        overrides_path = td_path / "overrides.yml"
        # seed a minimal overrides.yml
        shutil.copyfile("overrides.yml.example", overrides_path)

        # cd into td so the WantlistScreen.action_save writes into td/overrides.yml
        import os
        cwd = os.getcwd()
        os.chdir(td)
        try:
            app = RetrofetchApp(
                config=config,
                config_path=pathlib.Path("config.yml.example"),
                consoles_yml=consoles,
                overrides={"nes": load_overrides(overrides_path).get("nes") or load_overrides(overrides_path).get("nes", None)} if overrides_path.exists() else {},
            )
            # Inject a fake wantlist by monkey-patching ranker.get_wantlist BEFORE mount
            import retrofetch.ranker as ranker_mod
            _orig = ranker_mod.get_wantlist
            def fake_wantlist(*_, **__):
                return [f"Game {i}" for i in range(10)]
            # Also monkey-patch at the import site used by WantlistScreen
            import retrofetch.tui.screens.wantlist as ws_mod
            ws_mod.get_wantlist = fake_wantlist  # type: ignore[assignment]

            async with app.run_test() as pilot:
                await pilot.pause()
                # push the wantlist screen directly for a deterministic test
                screen = WantlistScreen(console_entry=entry, override=None)
                await app.push_screen(screen)
                await pilot.pause(0.3)

                # toggle include on first row
                await pilot.press("space")
                await pilot.pause()
                # toggle exclude on third row
                await pilot.press("down"); await pilot.press("down")
                await pilot.press("x")
                await pilot.pause()
                # save
                await pilot.press("s")
                await pilot.pause(0.5)

                # verify overrides.yml changed
                saved_text = overrides_path.read_text(encoding="utf-8")
                assert "Game 0" in saved_text or "include" in saved_text, f"expected include entries in overrides.yml, got: {saved_text[:400]}"
                print(f"T17 wantlist: OK (saved {len(saved_text)} bytes to overrides.yml)")
        finally:
            os.chdir(cwd)
            # restore ranker
            import retrofetch.tui.screens.wantlist as ws_mod
            ws_mod.get_wantlist = _orig  # type: ignore[assignment]


asyncio.run(main())
