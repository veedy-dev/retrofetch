"""U7: WantlistScreen mount does not freeze UI while wantlist loads."""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

REPO_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = REPO_ROOT / ".sisyphus" / "evidence" / "ux-task-7-wantlist-nonblocking.txt"

from retrofetch.config import Config, _yaml_rt
from retrofetch.tui.app import RetrofetchApp
from retrofetch.tui.screens.wantlist import WantlistScreen


async def main() -> None:
    repo_root = REPO_ROOT
    consoles_yml = _yaml_rt.load((repo_root / "consoles.yml").read_text(encoding="utf-8"))
    entries = consoles_yml.get("consoles", []) or []
    target = next(e for e in entries if str(e.get("class", "")) == "A")

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

            # Monkey-patch the wantlist screen's fetcher to sleep.
            import retrofetch.tui.screens.wantlist as ws_mod
            SLEEP_SEC = 1.2

            def slow_get_or_fetch(console_entry, overrides, config, limit):
                time.sleep(SLEEP_SEC)
                return (["Alpha", "Beta", "Gamma"], False)

            original = ws_mod.get_or_fetch_wantlist
            ws_mod.get_or_fetch_wantlist = slow_get_or_fetch
            try:
                async with app.run_test() as pilot:
                    await pilot.pause(0.3)
                    # Push WantlistScreen directly
                    ws = WantlistScreen(console_entry=target, override=None)
                    await app.push_screen(ws)
                    await pilot.pause(0.2)

                    # During the slow load, the UI must stay responsive.
                    t_start = time.time()
                    await pilot.press("tab")
                    await pilot.press("tab")
                    responsive_elapsed = time.time() - t_start
                    # Two tab presses should NOT take anywhere near SLEEP_SEC;
                    # if the UI thread were blocked, they would queue until load finished.
                    assert responsive_elapsed < (SLEEP_SEC * 0.7), (
                        f"UI appears blocked during load: two tab presses took {responsive_elapsed:.2f}s"
                    )

                    # Wait for load + message dispatch to complete.
                    await pilot.pause(SLEEP_SEC + 0.8)
                    # Table should be populated now
                    from textual.widgets import DataTable  # pyright: ignore[reportMissingImports]
                    table = ws.query_one("#wantlist-table", DataTable)
                    assert table.row_count == 3, f"expected 3 rows, got {table.row_count}"

                    app.exit(0)

                EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
                EVIDENCE.write_text(
                    "\n".join(
                        [
                            "status=PASS",
                            f"sleep_sec={SLEEP_SEC}",
                            f"ui_responsive_elapsed={responsive_elapsed:.3f}",
                            f"final_row_count={table.row_count}",
                        ]
                    ),
                    encoding="utf-8",
                )
                print("OK: wantlist screen nonblocking load (tabs responsive during sleep)")
            finally:
                ws_mod.get_or_fetch_wantlist = original
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
