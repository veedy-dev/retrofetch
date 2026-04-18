"""Global config editor — edit pydantic Config fields, save preserving YAML comments."""
from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult  # pyright: ignore[reportMissingImports]
from textual.binding import Binding  # pyright: ignore[reportMissingImports]
from textual.containers import Vertical, VerticalScroll  # pyright: ignore[reportMissingImports]
from textual.screen import Screen  # pyright: ignore[reportMissingImports]
from textual.widgets import Footer, Header, Input, Label  # pyright: ignore[reportMissingImports]

from retrofetch.config import _yaml_rt, save_config


# Editable scalar fields (restricted to pydantic schema, no arbitrary keys)
_EDITABLE_SCALARS = [
    ("roms_root", "string"),
    ("cache_dir", "string"),
    ("log_file", "string"),
    ("default_limit", "int"),
    ("max_concurrent_downloads", "int"),
]


class ConfigEditorScreen(Screen[None]):
    BINDINGS = [
        Binding("ctrl+s", "save", "Save", show=True),
        Binding("escape", "cancel", "Cancel", show=True),
    ]

    def __init__(self, *, config_path: Path) -> None:
        super().__init__()
        self.config_path = config_path
        self._raw = None  # loaded CommentedMap
        self._dirty = False
        self._status = ""

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Vertical(id="main-panel"):
            yield Label(
                f"Config: {self.config_path}. ctrl+s=save, esc=cancel.",
                id="cfg-title",
            )
            yield Label("", id="cfg-status")
            with VerticalScroll(id="cfg-form"):
                for field, _kind in _EDITABLE_SCALARS:
                    yield Label(field)
                    yield Input(id=f"cfg-{field}", placeholder=field)
        yield Footer()

    def on_mount(self) -> None:
        if self.config_path.exists():
            self._raw = _yaml_rt.load(self.config_path.read_text(encoding="utf-8"))
        else:
            self._raw = None
        for field, _kind in _EDITABLE_SCALARS:
            value = ""
            if self._raw is not None and field in self._raw:
                value = str(self._raw.get(field))
            self.query_one(f"#cfg-{field}", Input).value = value

    def on_input_changed(self, event: Input.Changed) -> None:
        input_id = event.input.id
        if input_id and input_id.startswith("cfg-"):
            self._dirty = True
            self._set_status("unsaved changes")

    def action_save(self) -> None:
        if self._raw is None:
            self._set_status("cannot save: config not loaded")
            return
        for field, kind in _EDITABLE_SCALARS:
            input_widget = self.query_one(f"#cfg-{field}", Input)
            val = input_widget.value
            if kind == "int":
                try:
                    self._raw[field] = int(val)
                except ValueError:
                    self._set_status(f"invalid int for {field}: {val!r}")
                    return
            else:
                self._raw[field] = val
        try:
            save_config(self.config_path, self._raw)
            self._dirty = False
            self._set_status(f"saved {self.config_path}")
        except Exception as exc:
            self._set_status(f"save failed: {exc}")

    def action_cancel(self) -> None:
        self.dismiss(None)

    def _set_status(self, msg: str) -> None:
        try:
            self.query_one("#cfg-status", Label).update(("* " if self._dirty else "") + msg)
        except Exception:
            # defensive: status Label may be unmounted during teardown
            pass
