"""U9 scenario: highlighting a class D/E/F console shows IDLE (no fetch).

This is the one truly-new U9 scenario. The other 7 U9 scenarios the plan
lists are already covered by earlier wave5-task{1,4,5,6,7,8}-*.py scripts:

- cleanroom-setup      -> wave5-task4-setup-save.py (and -cancel/-invalid)
- cache-hit            -> wave5-task6-home.py::scenario_cache_hit
- cache-miss           -> wave5-task1-cache.py (cold miss path)
- debounce             -> wave5-task6-home.py::scenario_debounce
- retry                -> wave5-task6-home.py::scenario_retry
- wantlist-nonblocking -> wave5-task7-wantlist-nonblocking.py
- download-nonblocking -> wave5-task8-download-nonblocking.py

Running this file verifies only the preview-class-def behavior. For the
full regression pass, see wave5-task9-regression.py.
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

REPO_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = REPO_ROOT / ".sisyphus" / "evidence" / "ux-task-9-preview-class-def.txt"

from retrofetch.config import Config, _yaml_rt
from retrofetch.tui.app import RetrofetchApp
from retrofetch.tui.widgets.wantlist_preview import WantlistPreview


async def main() -> None:
    consoles_yml = _yaml_rt.load((REPO_ROOT / "consoles.yml").read_text(encoding="utf-8"))
    cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td).resolve()
        os.chdir(td)
        try:
            config = Config(roms_root=td_path / "ROMs", cache_dir=td_path / "cache")
            app = RetrofetchApp(
                config=config,
                config_path=Path("config.yml"),
                consoles_yml=consoles_yml,
                overrides={},
                first_run=False,
            )

            # Count fetches — should be zero when highlighting class D/E/F.
            import retrofetch.tui.screens.home as home_mod
            calls: list[str] = []

            def fake_get_or_fetch(console_entry, overrides, config, limit):
                calls.append(str(console_entry.get("shortname", "")))
                return ([], False)

            original = home_mod.get_or_fetch_wantlist
            home_mod.get_or_fetch_wantlist = fake_get_or_fetch
            try:
                async with app.run_test() as pilot:
                    await pilot.pause(0.3)
                    list_view = app.screen.query_one("#console-list")
                    # Pick a class D/E/F console
                    skipped_idx = next(
                        (
                            i
                            for i, (e, _) in enumerate(app.screen._all_items)
                            if str(e.get("class", "")) in ("D", "E", "F")
                        ),
                        None,
                    )
                    assert skipped_idx is not None, "consoles.yml has no class D/E/F console"
                    skipped_shortname = str(app.screen._all_items[skipped_idx][0].get("shortname", ""))
                    skipped_klass = str(app.screen._all_items[skipped_idx][0].get("class", ""))

                    list_view.index = skipped_idx
                    # Wait longer than debounce to confirm NO worker fires.
                    await pilot.pause(1.2)

                    preview = app.screen.query_one("#main-panel", WantlistPreview)
                    state = preview.state
                    app.exit(0)

                assert calls == [], f"class D/E/F should not trigger fetch, got {calls}"
                assert state == "IDLE", f"preview state should be IDLE for class {skipped_klass}, got {state}"
                EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
                EVIDENCE.write_text(
                    "\n".join(
                        [
                            "status=PASS",
                            f"skipped_console={skipped_shortname}",
                            f"skipped_class={skipped_klass}",
                            f"worker_calls={calls}",
                            f"preview_state={state}",
                        ]
                    ),
                    encoding="utf-8",
                )
                print(f"OK: class {skipped_klass} console {skipped_shortname!r} shows IDLE (no fetch)")
            finally:
                home_mod.get_or_fetch_wantlist = original
        finally:
            os.chdir(cwd)


if __name__ == "__main__":
    import traceback
    try:
        asyncio.run(main())
    except AssertionError as exc:
        print(f"FAIL: {exc!r}", file=sys.stderr)
        traceback.print_exc()
        raise SystemExit(1)
