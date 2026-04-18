"""U8: DownloadScreen mount does not freeze UI while wantlist loads."""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

REPO_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = REPO_ROOT / ".sisyphus" / "evidence" / "ux-task-8-download-nonblocking.txt"

from retrofetch.config import Config, _yaml_rt
from retrofetch.tui.app import RetrofetchApp
from retrofetch.tui.screens.download import DownloadScreen


async def main() -> None:
    consoles_yml = _yaml_rt.load((REPO_ROOT / "consoles.yml").read_text(encoding="utf-8"))
    entries = consoles_yml.get("consoles", []) or []
    target = next(e for e in entries if str(e.get("class", "")) == "A")

    cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td).resolve()
        os.chdir(td)
        try:
            config = Config(roms_root=td_path / "ROMs", cache_dir=td_path / "cache")
            config.dry_run = True  # guarantee no real downloads
            app = RetrofetchApp(
                config=config,
                config_path=Path("config.yml"),
                consoles_yml=consoles_yml,
                overrides={},
                first_run=False,
            )

            import retrofetch.tui.screens.download as dl_mod
            SLEEP_SEC = 1.0

            def slow_get_or_fetch(console_entry, overrides, config, limit):
                time.sleep(SLEEP_SEC)
                return (["Alpha", "Beta"], False)

            original = dl_mod.get_or_fetch_wantlist
            dl_mod.get_or_fetch_wantlist = slow_get_or_fetch
            try:
                async with app.run_test() as pilot:
                    await pilot.pause(0.3)
                    ds = DownloadScreen(console_entry=target, override=None)
                    await app.push_screen(ds)
                    await pilot.pause(0.2)

                    from textual.widgets import Label  # pyright: ignore[reportMissingImports]
                    # Summary should show "Loading wantlist..." immediately (not blocked).
                    summary_before = str(ds.query_one("#summary-line", Label).render())
                    assert "Loading" in summary_before, f"expected 'Loading...' initially, got: {summary_before!r}"

                    t_start = time.time()
                    await pilot.press("tab")
                    await pilot.press("tab")
                    responsive_elapsed = time.time() - t_start
                    assert responsive_elapsed < (SLEEP_SEC * 0.7), (
                        f"UI appears blocked: two tab presses took {responsive_elapsed:.2f}s"
                    )

                    # Wait for load + message dispatch
                    await pilot.pause(SLEEP_SEC + 0.8)
                    summary_after = str(ds.query_one("#summary-line", Label).render())
                    assert "Ready to download" in summary_after, (
                        f"expected summary to become 'Ready to download ...', got: {summary_after!r}"
                    )
                    assert len(ds._wantlist) == 2

                    app.exit(0)

                EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
                EVIDENCE.write_text(
                    "\n".join(
                        [
                            "status=PASS",
                            f"sleep_sec={SLEEP_SEC}",
                            f"ui_responsive_elapsed={responsive_elapsed:.3f}",
                            f"summary_before={summary_before!r}",
                            f"summary_after={summary_after!r}",
                        ]
                    ),
                    encoding="utf-8",
                )
                print("OK: download screen nonblocking load (tabs responsive during sleep)")
            finally:
                dl_mod.get_or_fetch_wantlist = original
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
