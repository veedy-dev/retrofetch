"""Home screen: 178-console sidebar + filter + live wantlist preview panel.

The main panel is a :class:`WantlistPreview` that mirrors the currently
highlighted console. Highlight changes fire a 400ms-debounced worker that
reads :mod:`retrofetch.wantlist_cache` first (fresh hit skips network) and
falls through to ``ranker.get_wantlist`` on miss / stale / malformed cache.

Keybindings:
- ``Enter`` on a class A/B/C row -> ``ConsoleSelected`` (existing).
- Any highlight (arrow keys, page up/down) -> debounced preview fetch.
- ``Ctrl+R`` -> invalidate cache for the highlighted console and re-fetch.

Workers all carry explicit ``group=`` names per Metis K.6:
- ``preview`` for the Highlighted-debounced fetcher.
"""
from __future__ import annotations

# pyright: reportAttributeAccessIssue=false

from pathlib import Path
from typing import Any

from textual.app import ComposeResult  # pyright: ignore[reportMissingImports]
from textual.binding import Binding  # pyright: ignore[reportMissingImports]
from textual.containers import Horizontal, Vertical  # pyright: ignore[reportMissingImports]
from textual.message import Message  # pyright: ignore[reportMissingImports]
from textual.screen import Screen  # pyright: ignore[reportMissingImports]
from textual.widgets import Footer, Header, Input, Label, ListItem, ListView  # pyright: ignore[reportMissingImports]
from textual import work  # pyright: ignore[reportMissingImports, reportAttributeAccessIssue]

from retrofetch.state import load_state
from retrofetch.tui.messages import WantlistFailed, WantlistReady
from retrofetch.tui.widgets.wantlist_preview import WantlistPreview
from retrofetch.wantlist_cache import (
    get_or_fetch_wantlist,
    invalidate,
    is_recently_empty,
    load_cached,
)


class ConsoleSelected(Message):
    """Bubbled when the user selects a Class A/B/C console from the sidebar."""

    def __init__(self, shortname: str, display_name: str, klass: str) -> None:
        self.shortname = shortname
        self.display_name = display_name
        self.klass = klass
        super().__init__()


class HomeScreen(Screen[None]):
    CSS_PATH = "../styles.tcss"

    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
        Binding("slash", "focus_filter", "Filter", show=True, key_display="/"),
        Binding("question_mark", "help", "Help", show=True, key_display="?"),
        Binding("tab", "focus_next", "Next", show=False),
        Binding("w", "open_wantlist", "Wantlist", show=True),
        Binding("d", "open_download", "Download", show=True),
        Binding("b", "open_bios", "BIOS", show=True),
        Binding("s", "open_state", "State", show=True),
        Binding("C", "open_coverage", "Coverage", show=True),
        Binding("r", "retry_fetch", "Refresh", show=True),
        Binding("ctrl+r", "retry_fetch", "Refresh", show=False),
        # Left/right are unused by ListView (only up/down navigate rows); binding
        # them at the Screen level means the focused Input still gets cursor
        # movement inside its text field, but the ListView forwards to us.
        Binding("left", "preview_prev_page", "Prev page", show=True, key_display="<-"),
        Binding("right", "preview_next_page", "Next page", show=True, key_display="->"),
    ]

    # Debounce for filter Input.Changed events, per T2 spike.
    _FILTER_DEBOUNCE_MS = 200
    # Debounce for ListView.Highlighted auto-fetch, per UX plan (U6).
    _PREVIEW_DEBOUNCE_MS = 400
    # Upper bound on titles we ask any source for. The preview paginates
    # internally at WantlistPreview.PAGE_SIZE; the wantlist screen wants all
    # of them. 500 is practically "everything the source has".
    _PREVIEW_FETCH_LIMIT = 500

    def __init__(self) -> None:
        super().__init__()
        self._all_items: list[tuple[dict[str, Any], ListItem]] = []
        self._filter_timer = None
        self._preview_timer = None
        # Remember the last shortname whose preview we started to kick, so
        # Ctrl+R can re-trigger the same console without asking the ListView.
        self._last_highlighted: str | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Horizontal():
            with Vertical(id="sidebar"):
                yield Input(placeholder="filter consoles...", id="filter")
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
    def _is_available(cls, entry: dict[str, Any], cache_dir: Path | None = None) -> bool:
        """A console is 'available' iff:
        - its class is A/B/C, AND
        - at least one ranking source slug is populated, AND
        - no recent empty-marker exists (i.e. last fetch did not come back
          empty within EMPTY_MARKER_TTL_HOURS).

        ``cache_dir`` is optional so unit tests (and pre-mount callers) can
        invoke the classifier without requiring a config. When omitted, only
        the slug check is applied.
        """
        if not cls._has_slug(entry):
            return False
        if cache_dir is None:
            return True
        shortname = str(entry.get("shortname", ""))
        if not shortname:
            return False
        return not is_recently_empty(cache_dir, shortname)

    def on_mount(self) -> None:
        """Populate the ListView from self.app.consoles_yml (loaded by cli.py)."""
        consoles = self.app.consoles_yml.get("consoles", []) or []
        list_view: ListView = self.query_one("#console-list", ListView)
        cache_dir = self.app.config.cache_dir  # pyright: ignore[reportAttributeAccessIssue]
        total_count = 0
        available_count = 0
        for entry in consoles:
            shortname = str(entry.get("shortname", "?"))
            display_name = str(entry.get("display_name", shortname))
            klass = str(entry.get("class", "?"))
            available = self._is_available(entry, cache_dir)
            badge = f"[{klass}]" if klass else "[?]"
            label = Label(f"{badge} {display_name}")
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
        try:
            self.app.sub_title = f"{available_count}/{total_count} consoles available"
        except Exception:
            pass

    def _update_row_availability(self, shortname: str, available: bool) -> None:
        """Recolor a single sidebar row after a live fetch outcome.

        Used by the message handlers so a console that just returned 0 titles
        turns grey immediately, and a console whose retry succeeded turns
        green again without waiting for the next app launch.
        """
        changed = False
        for entry, item in self._all_items:
            if str(entry.get("shortname", "")) != shortname:
                continue
            prior = getattr(item, "_rf_available", False)
            if prior == available:
                return
            item._rf_available = available  # type: ignore[attr-defined]
            try:
                if available:
                    item.remove_class("class-unavailable")
                    item.add_class("class-available")
                else:
                    item.remove_class("class-available")
                    item.add_class("class-unavailable")
            except Exception:
                # Textual may not have mounted the item yet; ignore.
                pass
            changed = True
            break
        if changed:
            # Re-emit the coverage stat so the header reflects the new count.
            available_count = sum(
                1 for _, item in self._all_items if getattr(item, "_rf_available", False)
            )
            try:
                self.app.sub_title = f"{available_count}/{len(self._all_items)} consoles available"
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Filter debounce (unchanged)
    # ------------------------------------------------------------------
    def on_input_changed(self, event: Input.Changed) -> None:
        """Debounced filter."""
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

    # ------------------------------------------------------------------
    # Preview highlight debounce + auto-fetch (U6)
    # ------------------------------------------------------------------
    def _lookup_entry(self, shortname: str) -> dict[str, Any] | None:
        entries = self.app.consoles_yml.get("consoles", []) or []
        for entry in entries:
            if str(entry.get("shortname", "")) == shortname:
                return entry
        return None

    def _compute_state_counts(self, shortname: str) -> dict[str, int]:
        try:
            state = load_state(shortname, self.app.config.roms_root)
        except Exception:
            return {"acquired": 0, "unverified": 0, "failed": 0, "pending": 0}
        counts: dict[str, int] = {"acquired": 0, "unverified": 0, "failed": 0, "pending": 0}
        for game in state.games:
            status = getattr(game, "status", "pending")
            counts[status] = counts.get(status, 0) + 1
        return counts

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        """Debounced auto-fetch on console highlight (arrow keys / page up/down)."""
        item = event.item
        if item is None:
            return
        preview = self.query_one("#main-panel", WantlistPreview)
        # Cancel pending debounce regardless of class - new highlight supersedes.
        if self._preview_timer is not None:
            self._preview_timer.stop()
            self._preview_timer = None

        if not getattr(item, "_rf_available", False):
            # Skipped classes: no fetch, show IDLE placeholder.
            self._last_highlighted = None
            preview.show_idle()
            return

        shortname = str(getattr(item, "_rf_shortname", ""))
        if not shortname:
            return
        entry = self._lookup_entry(shortname)
        if entry is None:
            return
        self._last_highlighted = shortname

        # Cache fast-path: a fresh JSON read is O(few ms), safe on UI thread.
        cache_dir = self.app.config.cache_dir
        hit = load_cached(cache_dir, shortname)
        if hit is not None:
            counts = self._compute_state_counts(shortname)
            preview.show_ready(shortname, list(hit.titles), True, counts)
            return

        # Miss / stale -> show loading + schedule debounced worker.
        preview.show_loading(shortname)
        self._preview_timer = self.set_timer(
            self._PREVIEW_DEBOUNCE_MS / 1000.0,
            lambda e=entry: self._kick_preview_fetch(e),
        )

    @work(thread=True, exclusive=True, group="preview")
    def _kick_preview_fetch(self, entry: dict[str, Any]) -> None:
        """Background worker: fetch wantlist via cache, post result to self."""
        shortname = str(entry.get("shortname", ""))
        override = self.app.overrides.get(shortname)
        try:
            titles, from_cache = get_or_fetch_wantlist(
                console_entry=entry,
                overrides=override,
                config=self.app.config,
                limit=self._PREVIEW_FETCH_LIMIT,
            )
        except Exception as exc:
            self.post_message(WantlistFailed(shortname, str(exc)))
            return
        self.post_message(WantlistReady(shortname, titles, from_cache))

    # ------------------------------------------------------------------
    # Message handlers - run on UI thread
    # ------------------------------------------------------------------
    def on_wantlist_ready(self, message: WantlistReady) -> None:
        # Empty results downgrade the sidebar row to grey (in-session), so the
        # user knows this console is effectively unavailable. We still render
        # the (empty) preview so the user sees the outcome. Non-empty results
        # guarantee the row is green.
        self._update_row_availability(message.console, bool(message.titles))
        # Only accept if the highlighted console still matches, to avoid
        # stale worker results clobbering a newer highlight.
        if self._last_highlighted and message.console != self._last_highlighted:
            return
        counts = self._compute_state_counts(message.console)
        preview = self.query_one("#main-panel", WantlistPreview)
        # Pass the FULL title list - WantlistPreview handles pagination
        # internally (20 per page via PAGE_SIZE).
        preview.show_ready(
            message.console,
            list(message.titles),
            message.from_cache,
            counts,
        )

    def on_wantlist_failed(self, message: WantlistFailed) -> None:
        # Fetch failure also downgrades the row so the user sees the state
        # without needing to re-scroll.
        self._update_row_availability(message.console, False)
        if self._last_highlighted and message.console != self._last_highlighted:
            return
        try:
            self.app.show_toast(f"Fetch failed: {message.reason}", severity="warning")
        except Exception:
            # shutdown race: toast container may already be gone
            pass
        preview = self.query_one("#main-panel", WantlistPreview)
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
        if self._preview_timer is not None:
            self._preview_timer.stop()
            self._preview_timer = None
        # Retry kicks immediately (no debounce - user explicitly asked).
        self._kick_preview_fetch(entry)

    # ------------------------------------------------------------------
    # Existing Enter handler (unchanged)
    # ------------------------------------------------------------------
    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Enter on an item - post ConsoleSelected ONLY for class A/B/C."""
        item = event.item
        klass = getattr(item, "_rf_klass", "?")
        if not getattr(item, "_rf_available", False):
            return
        shortname = getattr(item, "_rf_shortname", "?")
        display_name = getattr(item, "_rf_display_name", "?")
        self.post_message(ConsoleSelected(shortname, display_name, klass))

    # ------------------------------------------------------------------
    # Existing action handlers (unchanged)
    # ------------------------------------------------------------------
    def action_focus_filter(self) -> None:
        self.query_one("#filter", Input).focus()

    def action_help(self) -> None:
        from retrofetch.tui.screens.help import HelpScreen
        self.app.push_screen(HelpScreen())

    def action_open_wantlist(self) -> None:
        list_view = self.query_one("#console-list", ListView)
        item = list_view.highlighted_child
        if item is None:
            return
        if not getattr(item, "_rf_available", False):
            return
        shortname = getattr(item, "_rf_shortname", "?")
        entry = self._lookup_entry(shortname)
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
        if not getattr(item, "_rf_available", False):
            return
        shortname = getattr(item, "_rf_shortname", "?")
        entry = self._lookup_entry(shortname)
        if entry is None:
            return
        override = self.app.overrides.get(shortname)
        from retrofetch.tui.screens.download_confirm import DownloadConfirmScreen
        self.app.push_screen(DownloadConfirmScreen(console_entry=entry, override=override))

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


