from __future__ import annotations

import asyncio
from pathlib import Path

from textual.app import App, ComposeResult
from textual.screen import Screen
from textual.widgets import Input, Label

from retrofetch import _resources
from retrofetch.config import Config, _yaml_rt, load_config, save_config
from retrofetch.tui.app import RetrofetchApp
from retrofetch.tui.screens.config_editor import ConfigEditorScreen
from retrofetch.tui.screens.setup import SetupScreen


class _BaseScreen(Screen[None]):
    def compose(self) -> ComposeResult:
        yield Label("base")


class _SettingsApp(App[None]):
    def __init__(self, screen: Screen, config: Config, config_path: Path) -> None:
        super().__init__()
        self.screen_to_push = screen
        self.config = config
        self.config_path = config_path

    async def on_mount(self) -> None:
        await self.push_screen(_BaseScreen())
        await self.push_screen(self.screen_to_push)


def _template(config_path: Path, config: Config) -> None:
    raw = _yaml_rt.load(
        _resources.find_data_file("config.yml.example").read_text(encoding="utf-8")
    )
    for field in Config.model_fields:
        value = getattr(config, field)
        if isinstance(value, Path):
            value = str(value)
        raw[field] = value
    save_config(config_path, raw)


def test_first_run_setup_saves_to_requested_user_path(scratch_path) -> None:
    config_path = scratch_path / "user-data" / "config.yml"
    defaults = Config(
        roms_root=scratch_path / "default-roms",
        bios_root=scratch_path / "default-bios",
        cache_dir=config_path.parent / "cache",
        log_file=config_path.parent / "retrofetch.log",
    )
    screen = SetupScreen(config_path=config_path, defaults=defaults)
    app = _SettingsApp(screen, defaults, config_path)
    chosen_roms = scratch_path / "My Games"
    chosen_bios = scratch_path / "My BIOS"

    async def run() -> None:
        async with app.run_test() as pilot:
            screen.query_one("#setup-roms-root", Input).value = str(chosen_roms)
            screen.query_one("#setup-bios-root", Input).value = str(chosen_bios)
            screen.query_one("#setup-limit", Input).value = "120"
            screen.query_one("#setup-concurrency", Input).value = "4"
            screen.action_save()
            await pilot.pause()

    asyncio.run(run())
    saved = load_config(config_path)
    assert saved.roms_root == chosen_roms
    assert saved.bios_root == chosen_bios
    assert saved.default_limit == 120
    assert saved.max_concurrent_downloads == 4
    assert chosen_roms.is_dir() and chosen_bios.is_dir()


def test_settings_save_applies_runtime_paths_immediately(scratch_path) -> None:
    config_path = scratch_path / "user-data" / "config.yml"
    original = Config(
        roms_root=scratch_path / "old-roms",
        bios_root=scratch_path / "old-bios",
        cache_dir=config_path.parent / "cache",
        log_file=config_path.parent / "retrofetch.log",
    )
    _template(config_path, original)
    screen = ConfigEditorScreen(config_path=config_path)
    app = _SettingsApp(screen, original, config_path)
    expected_root = config_path.parent

    async def run() -> None:
        async with app.run_test() as pilot:
            screen.query_one("#cfg-roms_root", Input).value = "new-roms"
            screen.query_one("#cfg-bios_root", Input).value = "new-bios"
            screen.query_one("#cfg-cache_dir", Input).value = "new-cache"
            screen.query_one("#cfg-default_limit", Input).value = "90"
            screen.action_save()
            await pilot.pause()

    asyncio.run(run())
    assert app.config.roms_root == expected_root / "new-roms"
    assert app.config.bios_root == expected_root / "new-bios"
    assert app.config.cache_dir == expected_root / "new-cache"
    assert app.config.log_file == expected_root / "retrofetch.log"
    assert app.config.default_limit == 90
    assert app.config.roms_root.is_dir()
    assert app.config.bios_root.is_dir()
    assert app.config.cache_dir.is_dir()
    assert load_config(config_path) == app.config


def test_limit_only_save_preserves_existing_relative_paths(scratch_path) -> None:
    config_path = scratch_path / "profile" / "config.yml"
    original = Config(
        roms_root=Path("ROMs"),
        bios_root=Path("BIOS"),
        cache_dir=Path(".cache"),
        log_file=Path("retrofetch.log"),
    )
    _template(config_path, original)
    screen = ConfigEditorScreen(config_path=config_path)
    app = _SettingsApp(screen, original, config_path)

    async def run() -> None:
        async with app.run_test() as pilot:
            screen.query_one("#cfg-default_limit", Input).value = "91"
            screen.action_save()
            await pilot.pause()

    asyncio.run(run())
    raw = _yaml_rt.load(config_path.read_text(encoding="utf-8"))
    assert raw["roms_root"] == "ROMs"
    assert raw["bios_root"] == "BIOS"
    assert raw["cache_dir"] == ".cache"
    assert raw["log_file"] == "retrofetch.log"
    assert app.config.roms_root == Path("ROMs")


def test_first_run_app_reloads_saved_config_before_home(scratch_path) -> None:
    config_path = scratch_path / "profile" / "config.yml"
    defaults = Config(
        roms_root=scratch_path / "default-roms",
        bios_root=scratch_path / "default-bios",
        cache_dir=config_path.parent / "cache",
        log_file=config_path.parent / "retrofetch.log",
    )

    class _ProbeApp(RetrofetchApp):
        CSS_PATH = Path(__file__).parents[1] / "retrofetch" / "tui" / "styles.tcss"
        opened_with: Config | None = None

        def _open_fresh_home(self) -> None:
            self.opened_with = self.config
            self.exit(0)

    app = _ProbeApp(
        config=defaults,
        config_path=config_path,
        overrides_path=config_path.with_name("overrides.yml"),
        consoles_yml={"consoles": []},
        overrides={},
        first_run=True,
    )
    chosen_roms = scratch_path / "chosen-roms"

    async def run() -> None:
        async with app.run_test() as pilot:
            setup = app.screen
            assert isinstance(setup, SetupScreen)
            setup.query_one("#setup-roms-root", Input).value = str(chosen_roms)
            setup.action_save()
            await pilot.pause()

    asyncio.run(run())
    assert app.opened_with is not None
    assert app.opened_with.roms_root == chosen_roms
    assert app.config == load_config(config_path)
