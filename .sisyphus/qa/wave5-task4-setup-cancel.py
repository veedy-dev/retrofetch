import os
import tempfile
from pathlib import Path

from retrofetch.cli import _REPO_DIR
from retrofetch.config import Config
from retrofetch.tui.app import RetrofetchApp
from retrofetch.tui.screens.setup import SetupScreen

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
            
            async with app.run_test() as pilot:
                await pilot.pause(0.3)
                assert isinstance(app.screen, SetupScreen)

                await pilot.press("escape")
                await pilot.pause(0.3)

            # App[int] stores the value passed to self.exit(code) in return_value.
            # cli.py then propagates it as the OS exit code.
            assert app.return_value == 2, f"expected return_value=2, got {app.return_value!r}"
            assert not (Path(td) / "config.yml").exists(), "config.yml should not exist on cancel"

            Path(cwd / ".sisyphus/evidence/ux-task-4-setup-cancel.txt").parent.mkdir(parents=True, exist_ok=True)
            Path(cwd / ".sisyphus/evidence/ux-task-4-setup-cancel.txt").write_text(
                f"return_value={app.return_value}\nstatus=PASS\n", encoding="utf-8"
            )
            print("OK: wave5-task4-setup-cancel")
        finally:
            os.chdir(cwd)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
