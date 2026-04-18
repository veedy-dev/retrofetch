import os
import tempfile
from pathlib import Path

from retrofetch.cli import _REPO_DIR
from retrofetch.config import Config, _yaml_rt
from retrofetch.tui.app import RetrofetchApp
from retrofetch.tui.screens.setup import SetupScreen
from textual.widgets import Input

async def main():
    cwd = Path.cwd()
    with tempfile.TemporaryDirectory() as td:
        os.chdir(td)
        try:
            assert not Path("config.yml").exists()
            
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
                
                screen = app.screen
                screen.query_one("#setup-roms-root", Input).value = f"{td}/ROMs"
                
                await pilot.press("ctrl+s")
                await pilot.pause(0.5)
                
                assert Path("config.yml").exists()
                
                data = _yaml_rt.load(Path("config.yml").read_text(encoding="utf-8"))
                assert data["roms_root"] == f"{td}/ROMs"
                
            Path(cwd / ".sisyphus/evidence/ux-task-4-setup-save.txt").parent.mkdir(parents=True, exist_ok=True)
            Path(cwd / ".sisyphus/evidence/ux-task-4-setup-save.txt").write_text("OK", encoding="utf-8")
            print("OK: wave5-task4-setup-save")
        finally:
            os.chdir(cwd)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
