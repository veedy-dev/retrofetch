import os
import tempfile
from pathlib import Path

from retrofetch.cli import _REPO_DIR
from retrofetch.config import Config
from retrofetch.tui.app import RetrofetchApp
from retrofetch.tui.screens.setup import SetupScreen
from textual.widgets import Input, Label

async def main():
    cwd = Path.cwd()
    with tempfile.TemporaryDirectory() as td:
        os.chdir(td)
        try:
            minimal_config = Config(roms_root=Path.cwd() / "ROMs")
            consoles_yml_path = _REPO_DIR / "consoles.yml"
            from retrofetch.cli import _load_consoles
            consoles_yml = _load_consoles(consoles_yml_path)
            
            app = RetrofetchApp(
                config=minimal_config,
                config_path=Path("config.yml"),
                consoles_yml=consoles_yml,
                overrides={},
                first_run=True,
            )
            
            status_text = ""
            async with app.run_test() as pilot:
                await pilot.pause(0.3)
                assert isinstance(app.screen, SetupScreen)

                screen = app.screen
                screen.query_one("#setup-limit", Input).value = "abc"

                await pilot.press("ctrl+s")
                await pilot.pause(0.3)

                assert isinstance(app.screen, SetupScreen), "screen should stay on stack"
                status_text = str(screen.query_one("#setup-status", Label).render())
                # force clean teardown of run_test
                app.exit(0)

            assert "invalid default_limit" in status_text, (
                f"status should mention invalid default_limit, got {status_text!r}"
            )
            assert not (Path(td) / "config.yml").exists(), "config.yml should not exist on invalid input"

            Path(cwd / ".sisyphus/evidence/ux-task-4-setup-invalid.txt").parent.mkdir(parents=True, exist_ok=True)
            Path(cwd / ".sisyphus/evidence/ux-task-4-setup-invalid.txt").write_text(
                f"status_text={status_text}\nstatus=PASS\n", encoding="utf-8"
            )
            print("OK: wave5-task4-setup-invalid")
        finally:
            os.chdir(cwd)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
