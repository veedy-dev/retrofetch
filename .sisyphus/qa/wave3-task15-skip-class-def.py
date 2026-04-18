from __future__ import annotations
import asyncio, pathlib
from retrofetch.config import load_config, load_overrides, _yaml_rt
from retrofetch.tui.app import RetrofetchApp
from retrofetch.tui.screens.home import ConsoleSelected


async def main() -> None:
    config = load_config(pathlib.Path("config.yml.example"))
    consoles = _yaml_rt.load(pathlib.Path("consoles.yml").read_text(encoding="utf-8"))
    app = RetrofetchApp(
        config=config,
        config_path=pathlib.Path("config.yml.example"),
        consoles_yml=consoles,
        overrides={},
    )

    received: list = []

    async with app.run_test() as pilot:
        await pilot.pause()

        # Find the HomeScreen
        screen = app.screen_stack[-1]

        # Hook a listener on ConsoleSelected (bubbles up to app level)
        original_post = app.post_message
        def capture(msg):
            if isinstance(msg, ConsoleSelected):
                received.append(msg)
            return original_post(msg)
        app.post_message = capture  # type: ignore[method-assign]

        # Find a Class D item ("mame" shortname — known to be Class D)
        from textual.widgets import ListView
        list_view = app.screen.query_one("#console-list", ListView)
        d_items = [i for i in list_view.children if getattr(i, "_rf_klass", "") in ("D", "E", "F")]
        assert d_items, "expected at least one class D/E/F item"
        target = d_items[0]

        # Simulate pressing enter on that item by calling on_list_view_selected with a mock
        # Since we're mocking, inject a fake Selected event:
        from textual.widgets import ListView as LV
        fake_event = LV.Selected(list_view=list_view, item=target, index=0)
        screen.on_list_view_selected(fake_event)  # type: ignore[attr-defined]
        await pilot.pause()

        assert not any(isinstance(m, ConsoleSelected) for m in received), \
            f"Class D/E/F item should not emit ConsoleSelected, but got {received}"

    print("T15 skip-class-def: OK (class D/E/F items don't emit ConsoleSelected)")


asyncio.run(main())
