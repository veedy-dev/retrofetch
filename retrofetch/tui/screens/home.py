"""Home screen: 178-console sidebar + filter + main panel placeholder."""
from __future__ import annotations

from typing import Any

from textual.app import ComposeResult  # pyright: ignore[reportMissingImports]
from textual.binding import Binding  # pyright: ignore[reportMissingImports]
from textual.containers import Horizontal, Vertical  # pyright: ignore[reportMissingImports]
from textual.message import Message  # pyright: ignore[reportMissingImports]
from textual.screen import Screen  # pyright: ignore[reportMissingImports]
from textual.widgets import Footer, Header, Input, Label, ListItem, ListView, Static  # pyright: ignore[reportMissingImports]


class ConsoleSelected(Message):
    """Bubbled when the user selects a Class A/B/C console from the sidebar."""

    def __init__(self, shortname: str, display_name: str, klass: str) -> None:
        self.shortname = shortname
        self.display_name = display_name
        self.klass = klass
        super().__init__()


class HomeScreen(Screen[None]):
    CSS_PATH = "../styles.tcss"  # inherit app-level styles; re-import here too if needed

    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
        Binding("slash", "focus_filter", "Filter", show=True, key_display="/"),
        Binding("question_mark", "help", "Help", show=True, key_display="?"),
        Binding("tab", "focus_next", "Next", show=False),
        Binding("w", "open_wantlist", "Wantlist", show=True),
        Binding("d", "open_download", "Download", show=True),
        Binding("s", "open_state", "State", show=True),
        Binding("C", "open_coverage", "Coverage", show=True),
    ]

    # Debounce for filter Input.Changed events, per T2 spike (200ms sweet spot).
    _FILTER_DEBOUNCE_MS = 200

    def __init__(self) -> None:
        super().__init__()
        self._all_items: list[tuple[dict[str, Any], ListItem]] = []
        self._filter_timer = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Horizontal():
            with Vertical(id="sidebar"):
                yield Input(placeholder="filter consoles...", id="filter")
                yield ListView(id="console-list")
            yield Static(
                "Select a console from the sidebar.\n\n"
                "[w] wantlist  [d] download  [s] state  [C] coverage  [?] help  [q] quit",
                id="main-panel",
            )
        yield Footer()

    def on_mount(self) -> None:
        """Populate the ListView from self.app.consoles_yml (loaded by cli.py)."""
        consoles = self.app.consoles_yml.get("consoles", []) or []
        list_view: ListView = self.query_one("#console-list", ListView)
        for entry in consoles:
            shortname = str(entry.get("shortname", "?"))
            display_name = str(entry.get("display_name", shortname))
            klass = str(entry.get("class", "?"))
            badge = f"[{klass}]" if klass else "[?]"
            label = Label(f"{badge} {display_name}")
            classes = ["console-row", f"class-{klass.lower()}"]
            if klass in ("D", "E", "F"):
                classes.append("class-def")
            item = ListItem(label, classes=" ".join(classes))
            # Stash metadata for later retrieval
            item._rf_shortname = shortname  # type: ignore[attr-defined]
            item._rf_display_name = display_name  # type: ignore[attr-defined]
            item._rf_klass = klass  # type: ignore[attr-defined]
            list_view.append(item)
            self._all_items.append((entry, item))

    def on_input_changed(self, event: Input.Changed) -> None:
        """Debounced filter — T2 verdict: 200ms."""
        if event.input.id != "filter":
            return
        if self._filter_timer is not None:
            self._filter_timer.stop()
        query = event.value.lower()
        self._filter_timer = self.set_timer(
            self._FILTER_DEBOUNCE_MS / 1000.0,
            lambda: self._apply_filter(query),
        )

    def _apply_filter(self, query: str) -> None:
        for _entry, item in self._all_items:
            display_name = getattr(item, "_rf_display_name", "").lower()
            shortname = getattr(item, "_rf_shortname", "").lower()
            matches = (not query) or (query in display_name) or (query in shortname)
            item.display = matches

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Enter on an item — post ConsoleSelected ONLY for class A/B/C."""
        item = event.item
        klass = getattr(item, "_rf_klass", "?")
        if klass in ("D", "E", "F"):
            return  # no-op: skipped classes are visually dimmed and non-selectable
        shortname = getattr(item, "_rf_shortname", "?")
        display_name = getattr(item, "_rf_display_name", "?")
        self.post_message(ConsoleSelected(shortname, display_name, klass))

    def action_focus_filter(self) -> None:
        self.query_one("#filter", Input).focus()

    def action_help(self) -> None:
        # T22 implements help screen; for now, no-op.
        pass

    def action_open_wantlist(self) -> None:
        list_view = self.query_one("#console-list", ListView)
        item = list_view.highlighted_child
        if item is None:
            return
        klass = getattr(item, "_rf_klass", "?")
        if klass in ("D", "E", "F"):
            return  # skipped classes can't open wantlist
        shortname = getattr(item, "_rf_shortname", "?")
        # Look up the full entry from consoles_yml
        entries = self.app.consoles_yml.get("consoles", []) or []
        entry = next((e for e in entries if str(e.get("shortname", "")) == shortname), None)
        if entry is None:
            return
        override = self.app.overrides.get(shortname)
        from retrofetch.tui.screens.wantlist import WantlistScreen
        self.app.push_screen(WantlistScreen(console_entry=entry, override=override))

    def action_open_download(self) -> None:
        list_view = self.query_one("#console-list", ListView)
        item = list_view.highlighted_child
        if item is None:
            return
        klass = getattr(item, "_rf_klass", "?")
        if klass in ("D", "E", "F"):
            return
        shortname = getattr(item, "_rf_shortname", "?")
        entries = self.app.consoles_yml.get("consoles", []) or []
        entry = next((e for e in entries if str(e.get("shortname", "")) == shortname), None)
        if entry is None:
            return
        override = self.app.overrides.get(shortname)
        from retrofetch.tui.screens.download import DownloadScreen
        self.app.push_screen(DownloadScreen(console_entry=entry, override=override))

    def action_open_state(self) -> None:
        list_view = self.query_one("#console-list")
        item = list_view.highlighted_child
        if item is None:
            return
        klass = getattr(item, "_rf_klass", "?")
        if klass in ("D", "E", "F"):
            return
        shortname = getattr(item, "_rf_shortname", "?")
        entries = self.app.consoles_yml.get("consoles", []) or []
        entry = next((e for e in entries if str(e.get("shortname", "")) == shortname), None)
        if entry is None:
            return
        from retrofetch.tui.screens.state import StateScreen
        self.app.push_screen(StateScreen(console_entry=entry))

    def action_open_coverage(self) -> None:
        from retrofetch.tui.screens.coverage import CoverageScreen
        self.app.push_screen(CoverageScreen())