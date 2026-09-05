"""Home screen: console sidebar and cache-first catalog preview.

The main panel mirrors the highlighted console. Cache hits render immediately,
then refresh once per session; cold catalogs load after a short debounce.

Keybindings:
- Enter on an available console opens its game browser.
- Any highlight (arrow keys, page up/down) -> cached or debounced live preview.
- ``Ctrl+R`` -> invalidate cache for the highlighted console and re-fetch.

Workers all carry explicit ``group=`` names per Metis K.6:
- ``preview`` for the Highlighted-debounced fetcher.
"""

from __future__ import annotations

# pyright: reportAttributeAccessIssue=false
from typing import Any

from textual import (
    work,  # pyright: ignore[reportMissingImports, reportAttributeAccessIssue]
)
from textual.app import ComposeResult  # pyright: ignore[reportMissingImports]
from textual.binding import Binding  # pyright: ignore[reportMissingImports]
from textual.containers import (  # pyright: ignore[reportMissingImports]
    Horizontal,
    Vertical,
)
from textual.screen import Screen  # pyright: ignore[reportMissingImports]
from textual.widgets import (  # pyright: ignore[reportMissingImports]
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
)

from retrofetch.tui.messages import QueueChanged, WantlistFailed, WantlistReady
from retrofetch.tui.widgets.wantlist_preview import WantlistPreview
from retrofetch.wantlist_cache import (
    get_or_fetch_wantlist,
    invalidate,
    load_cached,
    project_wantlist_titles,
)


class HomeScreen(Screen[None]):
    CSS_PATH = "../styles.tcss"

    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
        Binding(
            "slash", "focus_filter", "Search", show=True, key_display="/", priority=True
        ),
        Binding("question_mark", "help", "Help", show=True, key_display="?"),
        Binding("tab", "focus_next", "Next", show=False),
        Binding("g", "open_wantlist", "Browse games", show=True),
        Binding("d", "open_download", "Queue", show=True),
        Binding("b", "open_bios", "BIOS", show=True),
        Binding("s", "open_state", "History", show=True),
        Binding("comma", "open_settings", "Settings", show=True, key_display=","),
        Binding("C", "open_coverage", "Coverage", show=True),
        Binding("r", "retry_fetch", "Refresh", show=True),
        Binding("ctrl+r", "retry_fetch", "Refresh", show=False),
        # Left/right are unused by ListView (only up/down navigate rows); binding
        # them at the Screen level means the focused Input still gets cursor
        # movement inside its text field, but the ListView forwards to us.
        Binding("left", "preview_prev_page", "Prev page", show=True, key_display="<-"),
        Binding("right", "preview_next_page", "Next page", show=True, key_display="->"),
        Binding("escape", "leave_filter", "Results", show=False),
    ]

    # Debounce input and cold preview fetches so rapid navigation stays cheap.
    _FILTER_DEBOUNCE_MS = 200
    _PREVIEW_DEBOUNCE_MS = 250

    def __init__(self) -> None:
        super().__init__()
        self._all_items: list[tuple[dict[str, Any], ListItem]] = []
        self._filter_timer = None
        self._preview_timer = None
        self._last_highlighted: str | None = None
        self._preview_generation = 0
        self._preview_fetching: dict[str, int] = {}
        self._preview_refreshed: set[str] = set()

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Horizontal():
            with Vertical(id="sidebar"):
                yield Input(placeholder="search consoles...", id="filter")
                yield ListView(id="console-list")
            yield WantlistPreview(id="main-panel")
        yield Footer()

    _RANKING_SLUG_FIELDS = (
        "romsfun_slug",
        "romsretro_slug",
        "archive_org_identifier",
        "minerva_path",
        "vimm_slug",
        "coolrom_slug",
    )

    @classmethod
    def _has_slug(cls, entry: dict[str, Any]) -> bool:
        klass = str(entry.get("class", ""))
        if klass not in ("A", "B", "C"):
            return False
        return any(entry.get(field) for field in cls._RANKING_SLUG_FIELDS)

    @classmethod
    def _is_available(cls, entry: dict[str, Any]) -> bool:
        """Return whether a supported console has a browse adapter."""
        if cls._has_slug(entry):
            return True
        if str(entry.get("class", "")) not in ("A", "B", "C"):
            return False
        from retrofetch.sources.romsim import RomsimSource

        # Switch archives need no slug; reuse their network-free enablement.
        return RomsimSource(entry).enabled

    def on_mount(self) -> None:
        """Populate the ListView from self.app.consoles_yml (loaded by cli.py)."""
        consoles = self.app.consoles_yml.get("consoles", []) or []
        list_view: ListView = self.query_one("#console-list", ListView)
        total_count = 0
        available_count = 0
        for entry in consoles:
            shortname = str(entry.get("shortname", "?"))
            display_name = str(entry.get("display_name", shortname))
            klass = str(entry.get("class", "?"))
            available = self._is_available(entry)
            badge = f"[{klass}]" if klass else "[?]"
            label = Label(f"{badge} {display_name}", markup=False)
            css_class = "class-available" if available else "class-unavailable"
            classes = ["console-row", css_class]
            item = ListItem(label, classes=" ".join(classes))
            item._rf_shortname = shortname  # type: ignore[attr-defined]
            item._rf_display_name = display_name  # type: ignore[attr-defined]
            item._rf_klass = klass  # type: ignore[attr-defined]
            item._rf_available = available  # type: ignore[attr-defined]
            list_view.append(item)
            self._all_items.append((entry, item))
            total_count += 1
            if available:
                available_count += 1
        # Preview starts in IDLE state (WantlistPreview.on_mount handles it).
        # Use the header's sub_title slot to show a live coverage stat - that
        # fills the empty top-right corner with something useful.
        self.app.set_catalog_sub_title(
            f"{available_count}/{total_count} consoles available"
        )

    # ------------------------------------------------------------------
    # Filter debounce (unchanged)
    # ------------------------------------------------------------------
    def on_input_changed(self, event: Input.Changed) -> None:
        """Debounced filter."""
        if event.input.id != "filter":
            return
        if self._filter_timer is not None:
            self._filter_timer.stop()
        query = event.value.strip().casefold()
        self._filter_timer = self.set_timer(
            self._FILTER_DEBOUNCE_MS / 1000.0,
            lambda: self._apply_filter(query),
        )

    def _apply_filter(self, query: str) -> None:
        for _entry, item in self._all_items:
            display_name = getattr(item, "_rf_display_name", "").casefold()
            shortname = getattr(item, "_rf_shortname", "").casefold()
            matches = (not query) or (query in display_name) or (query in shortname)
            item.display = matches
        list_view = self.query_one("#console-list", ListView)
        highlighted = list_view.highlighted_child
        if highlighted is None or not highlighted.display:
            list_view.index = next(
                (
                    index
                    for index, (_, item) in enumerate(self._all_items)
                    if item.display
                ),
                None,
            )
            if list_view.index is None:
                self._last_highlighted = None
                self.query_one("#main-panel", WantlistPreview).show_idle()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "filter":
            self._apply_filter(event.value.strip().casefold())
            self.query_one("#console-list", ListView).focus()

    def action_leave_filter(self) -> None:
        self.query_one("#console-list", ListView).focus()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        return not (
            isinstance(self.focused, Input)
            and action not in {"focus_filter", "leave_filter", "focus_next"}
        )

    def on_queue_changed(self, message: QueueChanged) -> None:
        if message.console == self._last_highlighted:
            self._show_cached_preview(message.console)

    def on_screen_resume(self) -> None:
        if self._last_highlighted:
            self._show_cached_preview(self._last_highlighted)

    # ------------------------------------------------------------------
    # Cache-first preview
    # ------------------------------------------------------------------
    def _lookup_entry(self, shortname: str) -> dict[str, Any] | None:
        entries = self.app.consoles_yml.get("consoles", []) or []
        for entry in entries:
            if str(entry.get("shortname", "")) == shortname:
                return entry
        return None

    def _queue_counts(self, shortname: str) -> dict[str, int]:
        override = self.app.overrides.get(shortname)
        return {"queued": len(override.include) if override else 0}

    def _show_cached_preview(self, shortname: str) -> bool:
        hit = load_cached(self.app.config.cache_dir, shortname)
        if hit is None:
            return False
        override = self.app.overrides.get(shortname)
        titles = project_wantlist_titles(list(hit.titles), override, 0)
        self.query_one("#main-panel", WantlistPreview).show_ready(
            shortname, titles, self._queue_counts(shortname)
        )
        return True

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        """Show cached titles or fetch them after navigation settles."""
        item = event.item
        preview = self.query_one("#main-panel", WantlistPreview)
        if self._preview_timer is not None:
            self._preview_timer.stop()
            self._preview_timer = None
        self._preview_generation += 1
        request_id = self._preview_generation

        if item is None:
            self._last_highlighted = None
            preview.show_idle()
            return

        if not getattr(item, "_rf_available", False):
            # Skipped classes: no fetch, show IDLE placeholder.
            self._last_highlighted = None
            preview.show_idle()
            return

        shortname = str(getattr(item, "_rf_shortname", ""))
        if not shortname:
            self._last_highlighted = None
            preview.show_idle()
            return
        entry = self._lookup_entry(shortname)
        if entry is None:
            self._last_highlighted = None
            preview.show_idle()
            return
        self._last_highlighted = shortname

        cached = self._show_cached_preview(shortname)
        if not cached:
            preview.show_loading(shortname)
        if not cached or shortname not in self._preview_refreshed:
            self._preview_timer = self.set_timer(
                self._PREVIEW_DEBOUNCE_MS / 1000.0,
                lambda e=entry, r=request_id, refresh=cached: self._start_preview_fetch(
                    e, r, refresh
                ),
            )

    def _start_preview_fetch(
        self,
        entry: dict[str, Any],
        request_id: int,
        force_refresh: bool = False,
    ) -> None:
        shortname = str(entry.get("shortname", ""))
        if (
            not shortname
            or shortname != self._last_highlighted
            or shortname in self._preview_fetching
        ):
            return
        self._preview_refreshed.add(shortname)
        self._preview_fetching[shortname] = request_id
        self._kick_preview_fetch(entry, request_id, force_refresh)

    @work(thread=True, group="preview")
    def _kick_preview_fetch(
        self,
        entry: dict[str, Any],
        request_id: int,
        force_refresh: bool = False,
    ) -> None:
        """Background worker: fetch wantlist via cache, post result to self."""
        shortname = str(entry.get("shortname", ""))
        override = self.app.overrides.get(shortname)
        try:
            titles, from_cache = get_or_fetch_wantlist(
                console_entry=entry,
                overrides=override,
                config=self.app.config,
                limit=0,
                force_refresh=force_refresh,
            )
        except Exception as exc:
            self.post_message(WantlistFailed(shortname, str(exc), request_id))
            return
        if force_refresh and not titles:
            self.post_message(
                WantlistFailed(shortname, "refresh returned no titles", request_id)
            )
            return
        self.post_message(WantlistReady(shortname, titles, from_cache, request_id))

    # ------------------------------------------------------------------
    # Message handlers - run on UI thread
    # ------------------------------------------------------------------
    def on_wantlist_ready(self, message: WantlistReady) -> None:
        request_id = message.request_id
        if (
            request_id is None
            or self._preview_fetching.get(message.console) != request_id
        ):
            return
        del self._preview_fetching[message.console]
        if message.console != self._last_highlighted:
            return
        counts = self._queue_counts(message.console)
        preview = self.query_one("#main-panel", WantlistPreview)
        # Pass the FULL title list - WantlistPreview handles pagination
        # internally (20 per page via PAGE_SIZE).
        preview.show_ready(
            message.console,
            list(message.titles),
            counts,
        )

    def on_wantlist_failed(self, message: WantlistFailed) -> None:
        request_id = message.request_id
        if (
            request_id is None
            or self._preview_fetching.get(message.console) != request_id
        ):
            return
        del self._preview_fetching[message.console]
        if message.console != self._last_highlighted:
            return
        preview = self.query_one("#main-panel", WantlistPreview)
        if preview.state == "READY":
            return
        self.app.show_toast(f"Fetch failed: {message.reason}", severity="warning")
        preview.show_failed(message.console, message.reason)

    # ------------------------------------------------------------------
    # Retry binding (Ctrl+R)
    # ------------------------------------------------------------------
    def action_preview_next_page(self) -> None:
        try:
            preview = self.query_one("#main-panel", WantlistPreview)
        except Exception:
            return
        preview.next_page()

    def action_preview_prev_page(self) -> None:
        try:
            preview = self.query_one("#main-panel", WantlistPreview)
        except Exception:
            return
        preview.prev_page()

    def action_retry_fetch(self) -> None:
        shortname = self._last_highlighted
        if not shortname:
            return
        if shortname in self._preview_fetching:
            return
        entry = self._lookup_entry(shortname)
        if entry is None:
            return
        cache_dir = self.app.config.cache_dir
        try:
            invalidate(cache_dir, shortname)
        except Exception:
            # best-effort: invalidate failure should not block retry
            pass
        preview = self.query_one("#main-panel", WantlistPreview)
        preview.show_loading(shortname)
        self._preview_generation += 1
        request_id = self._preview_generation
        if self._preview_timer is not None:
            self._preview_timer.stop()
            self._preview_timer = None
        self._start_preview_fetch(entry, request_id)

    # ------------------------------------------------------------------
    # Console navigation
    # ------------------------------------------------------------------
    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.item.display and getattr(event.item, "_rf_available", False):
            self.action_open_wantlist()

    # ------------------------------------------------------------------
    # Screen actions
    # ------------------------------------------------------------------
    def action_focus_filter(self) -> None:
        self.query_one("#filter", Input).focus()

    def action_help(self) -> None:
        from retrofetch.tui.screens.help import HelpScreen

        self.app.push_screen(HelpScreen())

    def action_open_settings(self) -> None:
        from retrofetch.tui.screens.config_editor import ConfigEditorScreen

        def _saved(saved: bool | None) -> None:
            if saved:
                self.app.show_toast("Settings saved and applied.", "info")

        self.app.push_screen(
            ConfigEditorScreen(config_path=self.app.config_path), _saved
        )

    def action_open_wantlist(self) -> None:
        list_view = self.query_one("#console-list", ListView)
        item = list_view.highlighted_child
        if item is None or not item.display:
            return
        if not getattr(item, "_rf_available", False):
            return
        shortname = getattr(item, "_rf_shortname", "?")
        entry = self._lookup_entry(shortname)
        if entry is None:
            return
        override = self.app.overrides.get(shortname)
        from retrofetch.tui.screens.wantlist import WantlistScreen

        def refresh_preview(_: None) -> None:
            if self._last_highlighted != shortname:
                return
            if not self._show_cached_preview(shortname):
                self.query_one("#main-panel", WantlistPreview).show_loading(shortname)
                self._preview_generation += 1
                self._start_preview_fetch(entry, self._preview_generation)

        self.app.push_screen(
            WantlistScreen(console_entry=entry, override=override), refresh_preview
        )

    def action_open_download(self) -> None:
        list_view = self.query_one("#console-list", ListView)
        item = list_view.highlighted_child
        if item is None or not item.display:
            return
        if not getattr(item, "_rf_available", False):
            return
        shortname = getattr(item, "_rf_shortname", "?")
        entry = self._lookup_entry(shortname)
        if entry is None:
            return
        override = self.app.overrides.get(shortname)
        from retrofetch.tui.screens.download_confirm import DownloadConfirmScreen

        self.app.push_screen(
            DownloadConfirmScreen(console_entry=entry, override=override)
        )

    def action_open_bios(self) -> None:
        list_view = self.query_one("#console-list", ListView)
        item = list_view.highlighted_child
        if item is None:
            return
        klass = str(getattr(item, "_rf_klass", "?"))
        if klass not in ("A", "B", "C"):
            return
        shortname = getattr(item, "_rf_shortname", "?")
        entry = self._lookup_entry(shortname)
        if entry is None:
            return
        from retrofetch.tui.screens.bios import BiosScreen

        self.app.push_screen(BiosScreen(console_entry=entry))

    def action_open_state(self) -> None:
        list_view = self.query_one("#console-list")
        item = list_view.highlighted_child
        if item is None:
            return
        if not getattr(item, "_rf_available", False):
            return
        shortname = getattr(item, "_rf_shortname", "?")
        entry = self._lookup_entry(shortname)
        if entry is None:
            return
        from retrofetch.tui.screens.state import StateScreen

        self.app.push_screen(StateScreen(console_entry=entry))

    def action_open_coverage(self) -> None:
        from retrofetch.tui.screens.coverage import CoverageScreen

        self.app.push_screen(CoverageScreen())
