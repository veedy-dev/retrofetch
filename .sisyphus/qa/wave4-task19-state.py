"""Pilot: open StateScreen with a fixture state; assert 3 rows + status classes."""
from __future__ import annotations
import asyncio, json, pathlib, tempfile

from retrofetch.config import load_config, _yaml_rt
from retrofetch.tui.app import RetrofetchApp
from retrofetch.tui.screens.state import StateScreen


async def main() -> None:
    config = load_config(pathlib.Path("config.yml.example"))
    consoles = _yaml_rt.load(pathlib.Path("consoles.yml").read_text(encoding="utf-8"))
    entry = next(c for c in consoles["consoles"] if c["shortname"] == "nes")

    with tempfile.TemporaryDirectory() as td:
        td_path = pathlib.Path(td)
        roms_nes = td_path / "ROMs" / "nes"
        roms_nes.mkdir(parents=True)
        fixture = {
            "version": 1,
            "console": "nes",
            "games": [
                {"title": "A", "status": "acquired"},
                {"title": "B", "status": "unverified"},
                {"title": "C", "status": "failed"},
            ],
        }
        (roms_nes / ".retrofetch-state.json").write_text(json.dumps(fixture), encoding="utf-8")
        config.roms_root = td_path / "ROMs"

        app = RetrofetchApp(
            config=config,
            config_path=pathlib.Path("config.yml.example"),
            consoles_yml=consoles,
            overrides={},
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = StateScreen(console_entry=entry)
            await app.push_screen(screen)
            await pilot.pause(0.5)

            table = screen.query_one("#state-table")
            assert table.row_count == 3, f"expected 3 rows, got {table.row_count}"

            status_labels = list(screen.query(".status-cell"))
            classes_seen = set()
            for lbl in status_labels:
                classes_seen.update(lbl.classes)
            assert "status-acquired" in classes_seen, f"status-acquired missing: {classes_seen}"
            assert "status-unverified" in classes_seen, f"status-unverified missing: {classes_seen}"
            assert "status-failed" in classes_seen, f"status-failed missing: {classes_seen}"
    print("T19 state: OK (3 rows, status classes applied)")


asyncio.run(main())
