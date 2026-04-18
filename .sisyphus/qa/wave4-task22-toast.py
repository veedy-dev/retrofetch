"""Pilot: call app.show_toast('test', 'warning'); assert visible then gone after 4s."""
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
        app.show_toast("test toast", severity="warning")
        await pilot.pause(0.2)

        toasts = list(app.screen.query("Toast"))
        assert toasts, "toast not mounted"

        # Wait for the 3s auto-dismiss
        await pilot.pause(3.5)
        toasts_after = list(app.screen.query("Toast"))
        assert not toasts_after, f"toast not auto-dismissed after 3s: {toasts_after}"
    print("T22 toast: OK (mount + auto-dismiss)")


asyncio.run(main())
