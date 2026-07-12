"""Friendly runtime settings editor backed by config.yml."""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult  # pyright: ignore[reportMissingImports]
from textual.binding import Binding  # pyright: ignore[reportMissingImports]
from textual.containers import Vertical, VerticalScroll  # pyright: ignore[reportMissingImports]
from textual.screen import Screen  # pyright: ignore[reportMissingImports]
from textual.widgets import Footer, Header, Input, Label  # pyright: ignore[reportMissingImports]

from retrofetch.config import Config, _yaml_rt, save_config


_EDITABLE_SCALARS = [
    ("roms_root", "Game download folder", "path"),
    ("bios_root", "BIOS folder", "path"),
    ("cache_dir", "Cache folder", "path"),
    ("default_limit", "Games per console (1..1000)", "int"),
    ("max_concurrent_downloads", "Simultaneous downloads (1..16)", "int"),
    ("region_priority", "Region priority (comma-separated)", "csv"),
    ("extract_archives", "Extract archives (true/false)", "bool"),
    ("torrent_mode", "Torrent mode (managed/existing/disabled)", "torrent_mode"),
    ("qbittorrent_path", "qBittorrent executable (optional)", "optional_path"),
    ("qbittorrent_url", "qBittorrent API URL", "string"),
]


class ConfigEditorScreen(Screen[bool]):
    BINDINGS = [
        Binding("ctrl+s", "save", "Save", show=True),
        Binding("escape", "cancel", "Cancel", show=True),
    ]

    def __init__(self, *, config_path: Path) -> None:
        super().__init__()
        self.config_path = config_path
        self._raw = None
        self._dirty = False
        self._loading = True

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Vertical(id="main-panel"):
            yield Label("Settings. Ctrl+S=save and apply, Esc=cancel.", id="cfg-title")
            yield Label("", id="cfg-status")
            with VerticalScroll(id="cfg-form"):
                for field, label, _kind in _EDITABLE_SCALARS:
                    yield Label(label)
                    yield Input(id=f"cfg-{field}", placeholder=field)
        yield Footer()

    def on_mount(self) -> None:
        if self.config_path.exists():
            self._raw = _yaml_rt.load(self.config_path.read_text(encoding="utf-8"))
        if self._raw is None:
            self._raw = {}
        config = self.app.config  # pyright: ignore[reportAttributeAccessIssue]
        for field, _label, kind in _EDITABLE_SCALARS:
            raw_value = getattr(config, field)
            if kind == "csv":
                value = ",".join(str(part) for part in raw_value)
            elif kind == "bool":
                value = str(bool(raw_value)).lower()
            else:
                value = "" if raw_value is None else str(raw_value)
            self.query_one(f"#cfg-{field}", Input).value = value
        self._dirty = False
        self._loading = False
        self._set_status("")

    def on_input_changed(self, event: Input.Changed) -> None:
        input_id = event.input.id
        if not self._loading and input_id and input_id.startswith("cfg-"):
            self._dirty = True
            self._set_status("unsaved changes")

    def _absolute(self, value: str) -> str:
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = self.config_path.parent / path
        return path.resolve().as_posix()

    def action_save(self) -> None:
        if self._raw is None:
            self._set_status("settings are not loaded")
            return
        candidate = self._raw.copy()
        current = self.app.config  # pyright: ignore[reportAttributeAccessIssue]
        for field, _label, kind in _EDITABLE_SCALARS:
            val = self.query_one(f"#cfg-{field}", Input).value.strip()
            if kind == "int":
                try:
                    candidate[field] = int(val)
                except ValueError:
                    self._set_status(f"{field} must be a number")
                    return
            elif kind == "path":
                if not val:
                    self._set_status(f"{field} must not be empty")
                    return
                if val != str(getattr(current, field)):
                    candidate[field] = self._absolute(val)
            elif kind == "torrent_mode":
                if val not in {"managed", "existing", "disabled"}:
                    self._set_status(
                        "torrent_mode must be managed, existing, or disabled"
                    )
                    return
                candidate[field] = val
            elif kind == "optional_path":
                old = getattr(current, field)
                old_text = "" if old is None else str(old)
                if val != old_text:
                    candidate[field] = self._absolute(val) if val else None
            elif kind == "csv":
                values = [part.strip() for part in val.split(",") if part.strip()]
                if not values:
                    self._set_status("region_priority must not be empty")
                    return
                candidate[field] = values
            elif kind == "bool":
                if val.casefold() not in {"true", "false"}:
                    self._set_status(f"{field} must be true or false")
                    return
                candidate[field] = val.casefold() == "true"
            else:
                candidate[field] = val
        try:
            validated = Config(**candidate)
            validated.roms_root.mkdir(parents=True, exist_ok=True)
            validated.bios_root.mkdir(parents=True, exist_ok=True)
            validated.cache_dir.mkdir(parents=True, exist_ok=True)
            validated.log_file.parent.mkdir(parents=True, exist_ok=True)
            save_config(self.config_path, candidate)
            self.app.config = validated  # pyright: ignore[reportAttributeAccessIssue]
            self.dismiss(True)
        except Exception as exc:
            self._set_status(f"save failed: {exc}")

    def action_cancel(self) -> None:
        self.dismiss(False)

    def _set_status(self, message: str) -> None:
        try:
            marker = "* " if self._dirty and message else ""
            self.query_one("#cfg-status", Label).update(marker + message)
        except Exception:
            pass
