from __future__ import annotations

from pathlib import Path
from typing import Any

from textual.app import ComposeResult  # pyright: ignore[reportMissingImports]
from textual.binding import Binding  # pyright: ignore[reportMissingImports]
from textual.containers import Vertical  # pyright: ignore[reportMissingImports]
from textual.screen import Screen  # pyright: ignore[reportMissingImports]
from textual.widgets import Footer, Header, Input, Label, Static  # pyright: ignore[reportMissingImports]

from retrofetch import _resources
from retrofetch.config import _yaml_rt, save_config
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

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Vertical(id="setup-body"):
            yield Static("First-run Setup. All fields have sane defaults; adjust only if needed.")
            yield Label("ROMs root (absolute path):", classes="setup-label")
            yield Input(value=str(Path.cwd() / "ROMs"), id="setup-roms-root")
            yield Label("Default limit (1..1000):", classes="setup-label")
            yield Input(value="75", id="setup-limit")
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
        limit_text = self.query_one("#setup-limit", Input).value.strip()
        regions_text = self.query_one("#setup-regions", Input).value.strip()

        if not roms_root:
            self._set_status("roms_root must not be empty")
            return
        try:
            limit = int(limit_text)
        except ValueError:
            self._set_status(f"invalid default_limit: {limit_text!r}")
            return
        if not (1 <= limit <= 1000):
            self._set_status("default_limit must be between 1 and 1000")
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

        data["roms_root"] = roms_root
        data["default_limit"] = limit
        # Replace region_priority list in-place so ruamel retains comments/anchors.
        try:
            rp = data["region_priority"]
            rp.clear()
            for r in regions:
                rp.append(r)
        except Exception:
            data["region_priority"] = list(regions)

        target = Path("config.yml")
        try:
            save_config(target, data)
        except Exception as exc:
            self._set_status(f"save failed: {exc}")
            return

        self.app.post_message(SetupComplete(target))
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)
