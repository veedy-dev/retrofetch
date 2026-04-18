"""Per-console overrides editor — include/exclude/limit/region_priority, ruamel save."""
from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult  # pyright: ignore[reportMissingImports]
from textual.binding import Binding  # pyright: ignore[reportMissingImports]
from textual.containers import Vertical, VerticalScroll  # pyright: ignore[reportMissingImports]
from textual.screen import Screen  # pyright: ignore[reportMissingImports]
from textual.widgets import Footer, Header, Input, Label, TextArea  # pyright: ignore[reportMissingImports]

from retrofetch.config import _yaml_rt, save_overrides


class OverridesEditorScreen(Screen[None]):
    BINDINGS = [
        Binding("ctrl+s", "save", "Save", show=True),
        Binding("escape", "cancel", "Cancel", show=True),
    ]

    def __init__(self, *, overrides_path: Path, shortname: str) -> None:
        super().__init__()
        self.overrides_path = overrides_path
        self.shortname = shortname
        self._raw = None
        self._dirty = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Vertical(id="main-panel"):
            yield Label(
                f"Overrides [{self.shortname}] @ {self.overrides_path}. ctrl+s=save, esc=cancel.",
                id="ov-title",
            )
            yield Label("", id="ov-status")
            with VerticalScroll(id="ov-form"):
                yield Label("include (one title per line)")
                yield TextArea("", id="ov-include")
                yield Label("exclude (one title per line)")
                yield TextArea("", id="ov-exclude")
                yield Label("limit (blank = use config default)")
                yield Input(placeholder="75", id="ov-limit")
                yield Label("region_priority (comma-separated; blank = inherit)")
                yield Input(placeholder="USA,World,Europe,Japan", id="ov-regions")
        yield Footer()

    def on_mount(self) -> None:
        if self.overrides_path.exists():
            self._raw = _yaml_rt.load(self.overrides_path.read_text(encoding="utf-8"))
        if self._raw is None:
            self._raw = {}
        consoles = self._raw.get("consoles") or {}
        entry = consoles.get(self.shortname) or {}
        include = "\n".join(str(t) for t in (entry.get("include") or []))
        exclude = "\n".join(str(t) for t in (entry.get("exclude") or []))
        limit = entry.get("limit")
        region_priority = entry.get("region_priority") or []
        self.query_one("#ov-include", TextArea).text = include
        self.query_one("#ov-exclude", TextArea).text = exclude
        self.query_one("#ov-limit", Input).value = str(limit) if limit is not None else ""
        self.query_one("#ov-regions", Input).value = ",".join(str(r) for r in region_priority)

    def action_save(self) -> None:
        inc_text = self.query_one("#ov-include", TextArea).text
        exc_text = self.query_one("#ov-exclude", TextArea).text
        limit_text = self.query_one("#ov-limit", Input).value
        regions_text = self.query_one("#ov-regions", Input).value

        include = [t for t in inc_text.splitlines() if t.strip()]
        exclude = [t for t in exc_text.splitlines() if t.strip()]
        try:
            limit = int(limit_text) if limit_text.strip() else None
        except ValueError:
            self._set_status(f"invalid limit: {limit_text!r}")
            return
        region_priority = [r.strip() for r in regions_text.split(",") if r.strip()]

        from ruamel.yaml.comments import CommentedMap  # pyright: ignore[reportMissingImports]
        if self._raw is None:
            self._raw = CommentedMap()
        consoles = self._raw.get("consoles")
        if consoles is None:
            consoles = CommentedMap()
            self._raw["consoles"] = consoles
        entry = consoles.get(self.shortname)
        if entry is None:
            entry = CommentedMap()
            consoles[self.shortname] = entry
        entry["include"] = include
        entry["exclude"] = exclude
        if limit is None:
            entry.pop("limit", None)
        else:
            entry["limit"] = limit
        if region_priority:
            entry["region_priority"] = region_priority
        else:
            entry.pop("region_priority", None)

        try:
            save_overrides(self.overrides_path, self._raw)
            self._set_status(f"saved {self.overrides_path}")
        except Exception as exc:
            self._set_status(f"save failed: {exc}")

    def action_cancel(self) -> None:
        self.dismiss(None)

    def _set_status(self, msg: str) -> None:
        try:
            self.query_one("#ov-status", Label).update(msg)
        except Exception:
            # defensive: status Label may be unmounted during teardown
            pass
