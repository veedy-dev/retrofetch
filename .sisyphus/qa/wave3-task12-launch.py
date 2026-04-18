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
        statics = [w for w in app.query("Static")]
        assert statics, "no Static widgets found"
        contents = [getattr(s, "content", None) for s in statics]
        assert any("coming soon" in str(content).lower() for content in contents), \
            f"placeholder text not found in {contents}"
        await pilot.press("q")
        await pilot.pause()
    assert app.return_code == 0, f"expected 0, got {app.return_code}"
    print(f"T12 launch: OK (return_code={app.return_code})")

asyncio.run(main())
