from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding  # pyright: ignore[reportMissingImports]
from textual.containers import Vertical  # pyright: ignore[reportMissingImports]
from textual.screen import Screen  # pyright: ignore[reportMissingImports]
from textual.widgets import Footer, Header, Input, Label, Static  # pyright: ignore[reportMissingImports]

from retrofetch import _resources
from retrofetch.config import Config, _yaml_rt, save_config
from retrofetch.tui.messages import SetupComplete


class SetupScreen(Screen[bool]):
    BINDINGS = [
        Binding("ctrl+s", "save", "Save", show=True),
        Binding("escape", "cancel", "Cancel", show=True),
    ]

    DEFAULT_CSS = """
    SetupScreen #setup-body { padding: 1 2; }
    SetupScreen Label.setup-label { margin-top: 1; }
    SetupScreen #setup-status { margin-top: 1; color: $warning; }
    """

    def __init__(self, *, config_path: Path, defaults: Config) -> None:
        super().__init__()
        self.config_path = config_path
        self.defaults = defaults

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Vertical(id="setup-body"):
            yield Static(
                "Welcome to Retrofetch. Choose where games and BIOS files should be stored, then press Ctrl+S."
            )
            yield Label("Game download folder:", classes="setup-label")
            yield Input(value=str(self.defaults.roms_root), id="setup-roms-root")
            yield Label("BIOS folder:", classes="setup-label")
            yield Input(value=str(self.defaults.bios_root), id="setup-bios-root")
            yield Label("Games per console (1..1000):", classes="setup-label")
            yield Input(value=str(self.defaults.default_limit), id="setup-limit")
            yield Label("Simultaneous downloads (1..16):", classes="setup-label")
            yield Input(
                value=str(self.defaults.max_concurrent_downloads),
                id="setup-concurrency",
            )
            yield Label("Region priority (comma-separated):", classes="setup-label")
            yield Input(value="USA,World,Europe,Japan", id="setup-regions")
            yield Label("", id="setup-status")
        yield Footer()

    def _set_status(self, msg: str) -> None:
        try:
            self.query_one("#setup-status", Label).update(msg)
        except Exception:
            pass

    def action_save(self) -> None:
        roms_root = self.query_one("#setup-roms-root", Input).value.strip()
        bios_root = self.query_one("#setup-bios-root", Input).value.strip()
        limit_text = self.query_one("#setup-limit", Input).value.strip()
        concurrency_text = self.query_one("#setup-concurrency", Input).value.strip()
        regions_text = self.query_one("#setup-regions", Input).value.strip()

        if not roms_root or not bios_root:
            self._set_status("Game and BIOS folders must not be empty")
            return
        try:
            limit = int(limit_text)
            concurrency = int(concurrency_text)
        except ValueError:
            self._set_status(
                "Games per console and simultaneous downloads must be numbers"
            )
            return
        if not (1 <= limit <= 1000):
            self._set_status("default_limit must be between 1 and 1000")
            return
        if not (1 <= concurrency <= 16):
            self._set_status("Simultaneous downloads must be between 1 and 16")
            return
        regions = [r.strip() for r in regions_text.split(",") if r.strip()]
        if not regions:
            self._set_status("region_priority must not be empty")
            return

        example_path = _resources.find_data_file("config.yml.example")
        try:
            data = _yaml_rt.load(example_path.read_text(encoding="utf-8"))
        except Exception as exc:
            self._set_status(f"could not load template: {exc}")
            return

        def absolute(value: str) -> Path:
            path = Path(value).expanduser()
            if not path.is_absolute():
                path = self.config_path.parent / path
            return path.resolve()

        roms_path = absolute(roms_root)
        bios_path = absolute(bios_root)
        data["roms_root"] = roms_path.as_posix()
        data["bios_root"] = bios_path.as_posix()
        data["cache_dir"] = (self.config_path.parent / "cache").resolve().as_posix()
        data["log_file"] = (
            (self.config_path.parent / "retrofetch.log").resolve().as_posix()
        )
        data["default_limit"] = limit
        data["max_concurrent_downloads"] = concurrency
        # Replace region_priority list in-place so ruamel retains comments/anchors.
        try:
            rp = data["region_priority"]
            rp.clear()
            for r in regions:
                rp.append(r)
        except Exception:
            data["region_priority"] = list(regions)

        try:
            Config(**data)
            roms_path.mkdir(parents=True, exist_ok=True)
            bios_path.mkdir(parents=True, exist_ok=True)
            save_config(self.config_path, data)
        except Exception as exc:
            self._set_status(f"save failed: {exc}")
            return

        self.app.post_message(SetupComplete(self.config_path))
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)
