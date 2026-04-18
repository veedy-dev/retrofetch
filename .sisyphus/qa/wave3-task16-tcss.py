from __future__ import annotations
import asyncio, pathlib, re
from retrofetch.config import load_config, load_overrides, _yaml_rt
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

        # Sidebar width must be 32 (per TCSS rule)
        sidebar = app.screen.query_one("#sidebar")
        assert sidebar.styles.width is not None
        width_val = sidebar.styles.width.value
        assert width_val == 32, f"expected sidebar width 32, got {width_val}"

        # Stylesheet must have class-tier rules loaded
        sheet_text = "\n".join(str(rule) for rule in app.stylesheet.rules)
        assert ".class-a" in sheet_text or "class-a" in sheet_text, "class-a rule missing"
        assert ".class-b" in sheet_text or "class-b" in sheet_text, "class-b rule missing"
        assert ".class-c" in sheet_text or "class-c" in sheet_text, "class-c rule missing"
        assert ".status-acquired" in sheet_text or "status-acquired" in sheet_text, "status-acquired rule missing"

        # Check no emoji in raw TCSS
        tcss_path = pathlib.Path("retrofetch/tui/styles.tcss")
        content = tcss_path.read_text(encoding="utf-8")
        assert not re.search(r"[\U0001F300-\U0001FAFF]", content), "emoji found in TCSS"

        app.screen.set_focus(None)
        await pilot.press("q")
        await pilot.pause()

    assert app.return_code == 0

    print("T16 tcss: OK (sidebar width=32, class-tier rules loaded, no emoji)")


asyncio.run(main())
