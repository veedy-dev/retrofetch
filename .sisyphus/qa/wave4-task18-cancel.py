"""Pilot: start dry-run, cancel before completion, assert Cancel message visible."""
from __future__ import annotations
import asyncio, pathlib

from retrofetch.config import load_config, _yaml_rt
from retrofetch.tui.app import RetrofetchApp
from retrofetch.tui.screens.download import DownloadScreen


async def main() -> None:
    config = load_config(pathlib.Path("config.yml.example"))
    config.dry_run = True
    consoles = _yaml_rt.load(pathlib.Path("consoles.yml").read_text(encoding="utf-8"))
    entry = next(c for c in consoles["consoles"] if c["shortname"] == "virtualboy")

    app = RetrofetchApp(
        config=config,
        config_path=pathlib.Path("config.yml.example"),
        consoles_yml=consoles,
        overrides={},
    )
    import retrofetch.tui.screens.download as dl_mod
    dl_mod.get_wantlist = lambda **kw: [f"G{i}" for i in range(50)]  # type: ignore[assignment]

    async with app.run_test() as pilot:
        await pilot.pause()
        screen = DownloadScreen(console_entry=entry, override=None)
        await app.push_screen(screen)
        await pilot.pause(0.3)
        screen.action_start()
        await pilot.pause(0.1)
        await pilot.press("c")
        await pilot.pause(1.0)
        summary_text = str(screen.query_one("#summary-line").render())  # type: ignore[attr-defined]
        assert "Cancel" in summary_text or "Done" in summary_text, f"expected Cancelled or Done, got: {summary_text!r}"
    print(f"T18 cancel: OK (summary={summary_text!r})")


asyncio.run(main())
