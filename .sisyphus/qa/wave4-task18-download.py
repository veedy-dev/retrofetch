"""Pilot: dry-run through DownloadScreen; assert summary line updates with DownloadComplete."""
from __future__ import annotations
import asyncio, pathlib

from retrofetch.config import load_config, _yaml_rt
from retrofetch.tui.app import RetrofetchApp
from retrofetch.tui.screens.download import DownloadScreen


async def main() -> None:
    config = load_config(pathlib.Path("config.yml.example"))
    config.dry_run = True  # force dry run for QA (no network)
    consoles = _yaml_rt.load(pathlib.Path("consoles.yml").read_text(encoding="utf-8"))
    entry = next(c for c in consoles["consoles"] if c["shortname"] == "virtualboy")

    app = RetrofetchApp(
        config=config,
        config_path=pathlib.Path("config.yml.example"),
        consoles_yml=consoles,
        overrides={},
    )

    # Stub the @work cache-aware fetcher (new U8 call site) to avoid network.
    # Returns (titles, from_cache) tuple.
    import retrofetch.tui.screens.download as dl_mod
    dl_mod.get_or_fetch_wantlist = lambda **kw: (["Alpha", "Beta"], True)  # type: ignore[assignment]

    async with app.run_test() as pilot:
        await pilot.pause()
        screen = DownloadScreen(console_entry=entry, override=None)
        await app.push_screen(screen)
        # Wait for the @work wantlist-load worker to post WantlistReady; U8 made
        # this async so we pause longer before invoking action_start.
        await pilot.pause(1.0)

        # Start the download directly to bypass Checkbox focus consuming 'enter'
        screen.action_start()
        await pilot.pause(5.0)

        summary_text = str(screen.query_one("#summary-line").render())  # type: ignore[attr-defined]
        assert "Done" in summary_text or "attempted=2" in summary_text, f"unexpected summary: {summary_text!r}"
    print(f"T18 download: OK (summary={summary_text!r})")


asyncio.run(main())
