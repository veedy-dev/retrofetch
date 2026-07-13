from __future__ import annotations

import sys
from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding  # pyright: ignore[reportMissingImports]
from textual.containers import CenterMiddle, Horizontal, Vertical  # pyright: ignore[reportMissingImports]
from textual.screen import Screen  # pyright: ignore[reportMissingImports]
from textual.widgets import Button, Footer, Header, Input, Label, Static  # pyright: ignore[reportMissingImports]

from retrofetch import _resources
from retrofetch.config import Config, _yaml_rt, save_config
from retrofetch.tui.messages import SetupComplete


def select_directory(*, initial_dir: str, title: str) -> str | None:
    """Open the platform-native folder picker without adding a dependency."""
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError as exc:
        raise RuntimeError("Native folder picker is unavailable") from exc

    initial = Path(initial_dir).expanduser()
    if not initial.is_dir():
        initial = Path.home()

    root = None
    try:
        root = tk.Tk()
        root.withdraw()
        if sys.platform == "win32":
            root.attributes("-topmost", True)
        selected = filedialog.askdirectory(
            parent=root,
            title=title,
            initialdir=str(initial),
            mustexist=False,
        )
    except tk.TclError as exc:
        raise RuntimeError("Native folder picker could not be opened") from exc
    finally:
        if root is not None:
            root.destroy()
    return str(selected) if selected else None


class SetupScreen(Screen[bool]):
    BINDINGS = [
        Binding("ctrl+s", "save", "Save", show=True),
        Binding("escape", "cancel", "Cancel", show=True),
        Binding("question_mark", "help", "Help", show=True, key_display="?"),
    ]

    DEFAULT_CSS = """
    SetupScreen #setup-stage {
        height: 1fr;
        padding: 1 2;
    }
    SetupScreen #setup-card {
        width: 78;
        max-width: 96%;
        height: auto;
        padding: 0 1;
        background: $surface;
    }
    SetupScreen #setup-title {
        text-align: center;
        text-style: bold;
    }
    SetupScreen #setup-intro {
        text-align: center;
    }
    SetupScreen #setup-advanced {
        color: $text-muted;
        text-align: center;
        margin-bottom: 1;
    }
    SetupScreen .setup-field {
        height: auto;
        margin-top: 1;
        background: $surface;
    }
    SetupScreen .setup-field-title {
        color: $primary;
        text-style: bold;
    }
    SetupScreen .setup-hint {
        color: $text-muted;
    }
    SetupScreen .setup-path-row {
        height: 3;
    }
    SetupScreen .setup-path-row Input {
        width: 1fr;
        margin: 0;
        background: $surface-lighten-1;
    }
    SetupScreen .setup-browse {
        width: 12;
        margin-left: 1;
    }
    SetupScreen Button.setup-secondary.-style-flat {
        height: 3;
        color: $text;
        background: $surface-lighten-2;
        border: none;
    }
    SetupScreen Button.setup-secondary.-style-flat:hover {
        background: $primary-muted;
        border: none;
    }
    SetupScreen Button.setup-secondary.-style-flat:focus {
        color: $text;
        background: $primary;
        border: none;
        text-style: bold;
    }
    SetupScreen Button.setup-secondary.-style-flat.-active {
        background: $surface-lighten-1;
        border: none;
    }
    SetupScreen #setup-divider {
        height: 1;
        margin-top: 1;
        border-top: solid $surface-lighten-2;
    }
    SetupScreen #setup-picker-help {
        color: $text-muted;
    }
    SetupScreen #setup-actions {
        height: 3;
        margin-top: 1;
        align: center middle;
    }
    SetupScreen #setup-actions Button {
        width: 24;
        margin: 0 1;
    }
    SetupScreen #setup-status {
        height: 0;
        color: $error;
        text-align: center;
    }
    """

    def __init__(self, *, config_path: Path, defaults: Config) -> None:
        super().__init__()
        self.config_path = config_path
        self.defaults = defaults

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with CenterMiddle(id="setup-stage"):
            with Vertical(id="setup-card"):
                yield Static("Welcome to Retrofetch", id="setup-title")
                yield Static(
                    "Choose where your library should be stored.",
                    id="setup-intro",
                )
                yield Static(
                    "Advanced options can be changed later in Settings.",
                    id="setup-advanced",
                )
                with Vertical(classes="setup-field"):
                    yield Label("Games folder", classes="setup-field-title")
                    yield Static(
                        "Downloaded games will be saved here.", classes="setup-hint"
                    )
                    with Horizontal(classes="setup-path-row"):
                        yield Input(
                            value=str(self.defaults.roms_root), id="setup-roms-root"
                        )
                        yield Button(
                            "Browse...",
                            id="setup-browse-roms",
                            classes="setup-browse setup-secondary",
                            tooltip="Browse and manage game folders",
                            flat=True,
                        )
                yield Static("", id="setup-divider")
                with Vertical(classes="setup-field"):
                    yield Label("BIOS folder", classes="setup-field-title")
                    yield Static(
                        "Optional BIOS files will be saved here.",
                        classes="setup-hint",
                    )
                    with Horizontal(classes="setup-path-row"):
                        yield Input(
                            value=str(self.defaults.bios_root), id="setup-bios-root"
                        )
                        yield Button(
                            "Browse...",
                            id="setup-browse-bios",
                            classes="setup-browse setup-secondary",
                            tooltip="Browse and manage BIOS folders",
                            flat=True,
                        )
                yield Static(
                    "Browse opens your system folder picker.", id="setup-picker-help"
                )
                yield Label("", id="setup-status")
                with Horizontal(id="setup-actions"):
                    yield Button(
                        "Save & Continue", variant="primary", id="setup-save"
                    )
                    yield Button(
                        "Cancel",
                        id="setup-cancel",
                        classes="setup-secondary",
                        flat=True,
                    )
        yield Footer()

    def _set_status(self, msg: str) -> None:
        status = self.query_one("#setup-status", Label)
        status.update(msg)
        status.styles.height = 1 if msg else 0

    def action_save(self) -> None:
        roms_root = self.query_one("#setup-roms-root", Input).value.strip()
        bios_root = self.query_one("#setup-bios-root", Input).value.strip()

        if not roms_root or not bios_root:
            self._set_status("Game and BIOS folders must not be empty")
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
        data["default_limit"] = self.defaults.default_limit
        data["max_concurrent_downloads"] = self.defaults.max_concurrent_downloads
        # Replace region_priority list in-place so ruamel retains comments/anchors.
        try:
            rp = data["region_priority"]
            rp.clear()
            for r in self.defaults.region_priority:
                rp.append(r)
        except Exception:
            data["region_priority"] = list(self.defaults.region_priority)

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

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "setup-browse-roms":
            self._browse_for("#setup-roms-root", "Choose games folder")
        elif event.button.id == "setup-browse-bios":
            self._browse_for("#setup-bios-root", "Choose BIOS folder")
        elif event.button.id == "setup-save":
            self.action_save()
        elif event.button.id == "setup-cancel":
            self.action_cancel()

    def _browse_for(self, input_id: str, title: str) -> None:
        field = self.query_one(input_id, Input)
        try:
            selected = select_directory(initial_dir=field.value, title=title)
        except RuntimeError as exc:
            self._set_status(f"{exc}. Type the path manually.")
        else:
            if selected:
                field.value = selected
                self._set_status("")
        field.focus()

    def action_help(self) -> None:
        from retrofetch.tui.screens.help import HelpScreen

        self.app.push_screen(HelpScreen())

    def action_cancel(self) -> None:
        self.dismiss(False)
