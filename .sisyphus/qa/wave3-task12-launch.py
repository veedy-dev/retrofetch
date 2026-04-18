"""T12 launch scenario.

Originally asserted a 'coming soon' placeholder Static. After T15, on_mount
pushes HomeScreen (which has the 178-console sidebar) instead of the placeholder.
Updated to verify HomeScreen is active and the sidebar mounts, then q quits 0.
"""
from __future__ import annotations
import asyncio, pathlib
from retrofetch.config import load_config, load_overrides, _yaml_rt
from retrofetch.tui.app import RetrofetchApp
from retrofetch.tui.screens.home import HomeScreen


async def main() -> None:
    config = load_config(pathlib.Path("config.yml.example"))
    consoles = _yaml_rt.load(pathlib.Path("consoles.yml").read_text(encoding="utf-8"))
    overrides_path = pathlib.Path("overrides.yml.example")
    overrides = load_overrides(overrides_path) if overrides_path.exists() else {}
    app = RetrofetchApp(
        config=config,
        config_path=pathlib.Path("config.yml.example"),
        consoles_yml=consoles,
        overrides=overrides,
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        # HomeScreen should be the active screen after on_mount
        assert any(isinstance(s, HomeScreen) for s in app.screen_stack), \
            f"HomeScreen not in screen stack: {app.screen_stack}"
        # Sidebar must have populated the ListView with 178 consoles
        list_view = app.screen.query_one("#console-list")
        items = list(list_view.children)
        assert len(items) == 178, f"expected 178 console items, got {len(items)}"
        # HomeScreen auto-focuses its filter Input which consumes 'q' as text.
        # Blur focus so the screen-level 'q' binding fires (same pattern as T23 exit0).
        if app.focused is not None:
            app.set_focus(None)
        await pilot.pause(0.1)
        await pilot.press("q")
        await pilot.pause(0.2)
    assert app.return_code == 0, f"expected 0, got {app.return_code}"
    print(f"T12 launch: OK (HomeScreen pushed, 178 items, return_code={app.return_code})")


asyncio.run(main())
