"""Preview pagination + availability coloring + renamed app title."""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

REPO_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = REPO_ROOT / ".sisyphus" / "evidence" / "ux-wave7-pagination.txt"

from retrofetch.config import Config, _yaml_rt
from retrofetch.tui.app import RetrofetchApp
from retrofetch.tui.screens.home import HomeScreen
from retrofetch.tui.widgets.wantlist_preview import WantlistPreview


async def main() -> None:
    # 1. App title is "Retrofetch" (not "RetrofetchApp")
    assert RetrofetchApp.TITLE == "Retrofetch", f"expected TITLE='Retrofetch', got {RetrofetchApp.TITLE!r}"

    # 2. Availability classifier works
    has_slug = {"class": "A", "shortname": "x", "display_name": "X", "romsfun_slug": "foo"}
    no_slug = {"class": "A", "shortname": "x", "display_name": "X"}
    skipped = {"class": "D", "shortname": "x", "display_name": "X", "romsfun_slug": "foo"}
    assert HomeScreen._is_available(has_slug) is True
    assert HomeScreen._is_available(no_slug) is False
    assert HomeScreen._is_available(skipped) is False

    # 3. Pagination end-to-end via Home + monkey-patch
    repo_root = REPO_ROOT
    consoles_yml = _yaml_rt.load((repo_root / "consoles.yml").read_text(encoding="utf-8"))
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

            import retrofetch.tui.screens.home as home_mod
            fake_titles = [f"Title {i + 1}" for i in range(47)]

            def fake_get_or_fetch(**_kwargs):
                return (list(fake_titles), True)

            original = home_mod.get_or_fetch_wantlist
            home_mod.get_or_fetch_wantlist = fake_get_or_fetch
            page1_text = page2_text = page3_text = page3_bounds = page2_back = ""
            try:
                async with app.run_test() as pilot:
                    await pilot.pause(0.3)
                    list_view = app.screen.query_one("#console-list")
                    eligible = [
                        i for i, (e, _) in enumerate(app.screen._all_items)
                        if HomeScreen._is_available(e)
                    ]
                    assert eligible, "no available consoles found in consoles.yml"
                    list_view.index = eligible[0]
                    await pilot.pause(0.6)

                    preview = app.screen.query_one("#main-panel", WantlistPreview)
                    assert preview.state == "READY", f"preview not READY, got {preview.state}"
                    assert len(preview._titles) == 47, f"expected 47 titles cached, got {len(preview._titles)}"

                    page1_text = str(preview.render())
                    app.screen.action_preview_next_page()
                    await pilot.pause(0.1)
                    page2_text = str(preview.render())
                    app.screen.action_preview_next_page()
                    await pilot.pause(0.1)
                    page3_text = str(preview.render())
                    # next beyond last is a no-op
                    app.screen.action_preview_next_page()
                    await pilot.pause(0.1)
                    page3_bounds = str(preview.render())
                    # prev back to page 2
                    app.screen.action_preview_prev_page()
                    await pilot.pause(0.1)
                    page2_back = str(preview.render())
                    app.exit(0)
            finally:
                home_mod.get_or_fetch_wantlist = original

            assert "Page 1/3" in page1_text and "Title 1" in page1_text and "Title 20" in page1_text
            assert "Title 21" not in page1_text
            assert "Page 2/3" in page2_text and "Title 21" in page2_text and "Title 40" in page2_text
            assert "Page 3/3" in page3_text and "Title 41" in page3_text and "Title 47" in page3_text
            # Bounds: next beyond last stays on page 3
            assert "Page 3/3" in page3_bounds, "next_page() should not wrap past last page"
            # Prev returns to page 2
            assert "Page 2/3" in page2_back, "prev_page() from page 3 should land on page 2"

            EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
            EVIDENCE.write_text(
                "\n".join(
                    [
                        "status=PASS",
                        f"app_title={RetrofetchApp.TITLE}",
                        "availability_classifier=OK",
                        "pagination_1/3=OK",
                        "pagination_2/3=OK",
                        "pagination_3/3=OK",
                        "next_past_end=bounds_OK",
                        "prev_from_last=OK",
                    ]
                ),
                encoding="utf-8",
            )
            print("OK: wave7 pagination + availability + title rename")
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
