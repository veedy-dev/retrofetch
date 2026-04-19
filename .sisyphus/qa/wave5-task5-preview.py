from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from textual.app import App, ComposeResult  # pyright: ignore[reportMissingImports]

from retrofetch.tui.widgets.wantlist_preview import WantlistPreview


class HarnessApp(App):
    def compose(self) -> ComposeResult:
        yield WantlistPreview(id="preview")


def _read_text(preview: WantlistPreview) -> str:
    # Static exposes `renderable`; fall back to `render()` if API drifts.
    r = getattr(preview, "renderable", None)
    if r is None:
        r = preview.render()
    return str(r)


def _write_evidence(text: str) -> None:
    p = Path(".sisyphus/evidence/ux-task-5-preview.txt")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


async def main() -> None:
    app = HarnessApp()
    async with app.run_test() as pilot:
        await pilot.pause(0.2)
        preview = app.query_one("#preview", WantlistPreview)

        # IDLE (on_mount defaults to IDLE)
        assert preview.state == "IDLE", f"expected IDLE, got {preview.state}"
        idle_text = _read_text(preview)
        assert "Select a console from the sidebar" in idle_text
        assert "[w] wantlist" in idle_text

        # LOADING
        preview.show_loading("nes")
        await pilot.pause(0.05)
        assert preview.state == "LOADING"
        loading_text = _read_text(preview)
        assert "Fetching wantlist for nes" in loading_text
        assert "[w] wantlist" in loading_text  # hints always visible

        # READY cached
        preview.show_ready(
            "nes",
            ["Super Mario Bros.", "The Legend of Zelda", "Metroid"],
            from_cache=True,
            state_counts={"acquired": 1, "failed": 0, "pending": 2, "unverified": 0},
        )
        await pilot.pause(0.05)
        assert preview.state == "READY"
        ready_text = _read_text(preview)
        assert "nes - 3 titles (cached)" in ready_text, f"header missing, got: {ready_text[:200]!r}"
        assert "Super Mario Bros." in ready_text
        assert "The Legend of Zelda" in ready_text
        assert "acquired=1" in ready_text
        assert "failed=0" in ready_text
        assert "pending=2" in ready_text
        assert "[w] wantlist" in ready_text

        # READY fresh with >20 titles: pagination (page 1/2, 20 titles visible)
        big_titles = [f"Title {i}" for i in range(25)]
        preview.show_ready("snes", big_titles, from_cache=False, state_counts={"acquired": 0, "failed": 0, "pending": 25})
        await pilot.pause(0.05)
        big_text = _read_text(preview)
        assert "snes - 25 titles (fresh)" in big_text
        assert "Title 0" in big_text  # first shown on page 1
        assert "Title 19" in big_text  # 20th shown on page 1
        assert "Title 20" not in big_text  # on page 2, not shown yet
        assert "Page 1/2" in big_text, f"missing page indicator, got: {big_text[:300]!r}"
        # Next page shows remaining 5 titles with global numbering 21..25
        preview.next_page()
        await pilot.pause(0.05)
        page2_text = _read_text(preview)
        assert "Title 20" in page2_text
        assert "Title 24" in page2_text  # 25th global
        assert "Page 2/2" in page2_text
        # Prev back to page 1
        preview.prev_page()
        await pilot.pause(0.05)
        assert "Page 1/2" in _read_text(preview)

        # FAILED
        preview.show_failed("nes", "network unreachable")
        await pilot.pause(0.05)
        assert preview.state == "FAILED"
        failed_text = _read_text(preview)
        assert "Fetch failed for nes: network unreachable" in failed_text
        assert "Retry" in failed_text
        assert "Ctrl+R" in failed_text

        # Back to IDLE
        preview.show_idle()
        await pilot.pause(0.05)
        assert preview.state == "IDLE"
        idle_again = _read_text(preview)
        assert "Select a console" in idle_again

        app.exit(0)

    _write_evidence(
        "status=PASS\n"
        "modes=IDLE,LOADING,READY(cached),READY(fresh,truncated),FAILED,IDLE\n"
    )
    print("OK: WantlistPreview lifecycle across IDLE/LOADING/READY/FAILED modes")


if __name__ == "__main__":
    import traceback
    try:
        asyncio.run(main())
    except AssertionError as exc:
        print(f"FAIL: {exc!r}", file=sys.stderr)
        traceback.print_exc()
        raise SystemExit(1)
