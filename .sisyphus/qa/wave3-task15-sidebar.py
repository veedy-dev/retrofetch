from __future__ import annotations
import asyncio, pathlib
from retrofetch.config import load_config, load_overrides, _yaml_rt
from retrofetch.tui.app import RetrofetchApp


async def main() -> None:
    config = load_config(pathlib.Path("config.yml.example"))
    consoles = _yaml_rt.load(pathlib.Path("consoles.yml").read_text(encoding="utf-8"))
    overrides_path = pathlib.Path("overrides.yml.example")
    overrides = load_overrides(overrides_path) if overrides_path.exists() else {}

    app = RetrofetchApp(
        config=config,
        config_path=pathlib.Path("config.yml.example"),
        consoles_yml=consoles,
        overrides=overrides,
    )

    async with app.run_test() as pilot:
        await pilot.pause()
        list_view = app.screen.query_one("#console-list")
        # 178 items rendered
        items = list(list_view.children)
        assert len(items) == 178, f"expected 178 console items, got {len(items)}"

        # Filter 'nintendo' → debounced to 200ms
        filter_input = app.screen.query_one("#filter")
        filter_input.value = "nintendo"
        await pilot.pause(0.4)  # wait for 200ms debounce + headroom

        visible = [i for i in list_view.children if i.display]
        assert 5 <= len(visible) <= 30, f"expected 5-30 nintendo-matching visible items, got {len(visible)}"

        # Clear filter
        filter_input.value = ""
        await pilot.pause(0.4)
        visible_all = [i for i in list_view.children if i.display]
        assert len(visible_all) == 178, f"expected 178 after clear, got {len(visible_all)}"

        # Quit
        app.screen.set_focus(None)
        await pilot.press("q")
        await pilot.pause()

    assert app.return_code == 0, f"expected 0 on q quit, got {app.return_code}"
    print(f"T15 sidebar: OK (178 items, nintendo-filter yields valid subset)")


asyncio.run(main())
