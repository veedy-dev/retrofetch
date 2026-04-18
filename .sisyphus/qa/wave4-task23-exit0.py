"""T23 exit0: `q` binding produces exit 0 via Pilot.

Implementation note: HomeScreen auto-focuses its filter Input on mount, which
consumes printable keystrokes (including `q`) as text input. The screen-level
binding `q->quit` therefore only fires when focus is NOT on the Input. We
blur focus via `app.set_focus(None)` before pressing `q` so the binding
reaches `App.action_quit` and the exit 0 path is exercised end-to-end.
"""
from __future__ import annotations
import asyncio, pathlib

from retrofetch.config import load_config, _yaml_rt
from retrofetch.tui.app import RetrofetchApp


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
        if app.focused is not None:
            app.set_focus(None)
        await pilot.pause(0.1)
        await pilot.press("q")
        await pilot.pause(0.2)
    assert app.return_code == 0, f"expected 0, got {app.return_code}"
    print(f"T23 exit0: OK (return_code={app.return_code})")


asyncio.run(main())
