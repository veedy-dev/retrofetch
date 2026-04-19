"""Wantlist curation screen - DataTable multi-select + save to overrides.yml.

Pushed from HomeScreen when the user presses 'w' on a selected Class A/B/C console.
Displays up to 200 ranked titles with include/exclude state, paginated 50 rows/page
(T1 verdict: raw DataTable filtering is NO-GO at 5000 rows; paginate instead).

Save path: load overrides.yml via _yaml_rt (load-then-mutate per Metis K.4), update
the specific console's include/exclude lists, save via save_overrides() (atomic LF).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from textual import work  # pyright: ignore[reportMissingImports, reportAttributeAccessIssue]
from textual.app import ComposeResult  # pyright: ignore[reportMissingImports]
from textual.binding import Binding  # pyright: ignore[reportMissingImports]
from textual.containers import Horizontal, Vertical  # pyright: ignore[reportMissingImports]
from textual.screen import Screen  # pyright: ignore[reportMissingImports]
from textual.widgets import DataTable, Footer, Header, Label, Static  # pyright: ignore[reportMissingImports]

from retrofetch.config import ConsoleOverride, _yaml_rt, save_overrides
from retrofetch.tui.messages import WantlistFailed, WantlistReady
from retrofetch.wantlist_cache import get_or_fetch_wantlist


class WantlistScreen(Screen[None]):
    BINDINGS = [
        Binding("space", "toggle_include", "Include", show=True),
        Binding("x", "toggle_exclude", "Exclude", show=True),
        Binding("s", "save", "Save", show=True),
        Binding("r", "refresh", "Refresh", show=True),
        Binding("escape", "cancel", "Cancel", show=True),
        Binding("pageup", "page_prev", "Prev page", show=True),
        Binding("pagedown", "page_next", "Next page", show=True),
    ]

    _PAGE_SIZE = 50

    def __init__(
        self,
        *,
        console_entry: dict[str, Any],
        override: ConsoleOverride | None,
    ) -> None:
        super().__init__()
        self.console_entry = console_entry
        self.shortname = str(console_entry.get("shortname", "?"))
        self.override = override or ConsoleOverride()
        # Working copies so esc can discard unsaved changes
        self._include: set[str] = set(self.override.include)
        self._exclude: set[str] = set(self.override.exclude)
        self._wantlist: list[str] = []
        self._page = 0
        self._status = ""
        self._primary_source: str = "-"
        self._loaded_source: str = ""  # "cached" / "fresh" / "error" / ""

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Vertical(id="main-panel"):
            yield Label(
                f"Wantlist: {self.shortname}  (space=include, x=exclude, s=save, r=refresh, esc=cancel)"
            )
            yield Label("", id="status-line")
            yield DataTable(id="wantlist-table")
        yield Footer()

    def on_mount(self) -> None:
        table: DataTable = self.query_one("#wantlist-table", DataTable)
        table.add_columns("#", "sel", "Title", "Source", "Included", "Excluded")
        table.cursor_type = "row"
        klass = str(self.console_entry.get("class", "?"))
        ranking_sources = self.app.config.ranking_sources_by_class.get(klass, [])  # pyright: ignore[reportAttributeAccessIssue]
        self._primary_source = ranking_sources[0] if ranking_sources else "-"
        # Kick background loader. UI remains responsive; handler fills the table.
        self._set_status("Loading wantlist...")
        self._kick_load()

    @work(thread=True, exclusive=True, group="wantlist-load")
    def _kick_load(self) -> None:
        try:
            titles, from_cache = get_or_fetch_wantlist(
                console_entry=self.console_entry,
                overrides=None,  # raw ranking; UI applies user's include/exclude
                config=self.app.config,  # pyright: ignore[reportAttributeAccessIssue]
                limit=200,
            )
        except Exception as exc:
            self.post_message(WantlistFailed(self.shortname, str(exc)))
            return
        self.post_message(WantlistReady(self.shortname, titles, from_cache))

    def on_wantlist_ready(self, message: WantlistReady) -> None:
        if message.console != self.shortname:
            return
        self._wantlist = list(message.titles)
        self._loaded_source = "cached" if message.from_cache else "fresh"
        self._page = 0
        self._render_page()

    def on_wantlist_failed(self, message: WantlistFailed) -> None:
        if message.console != self.shortname:
            return
        self._wantlist = []
        self._loaded_source = "error"
        self._set_status(f"error: {message.reason}")
        self._render_page()

    def _render_page(self) -> None:
        table: DataTable = self.query_one("#wantlist-table", DataTable)
        table.clear()
        start = self._page * self._PAGE_SIZE
        end = start + self._PAGE_SIZE
        page_rows = self._wantlist[start:end]
        for offset, title in enumerate(page_rows):
            inc = "[x]" if title in self._include else "[ ]"
            exc = "[x]" if title in self._exclude else "[ ]"
            table.add_row(
                str(start + offset + 1),
                inc,
                title,
                self._primary_source,
                "yes" if title in self._include else "",
                "yes" if title in self._exclude else "",
            )
        # Reset the viewport to the top on each page render so rows are never
        # stranded mid-scroll.
        try:
            if page_rows:
                table.cursor_coordinate = (0, 0)
                table.scroll_home(animate=False)
        except Exception:
            # Textual API variant: scroll_home might differ
            pass
        self._refresh_status_line()

    def _refresh_status_line(self) -> None:
        total = len(self._wantlist)
        total_pages = max(1, (total + self._PAGE_SIZE - 1) // self._PAGE_SIZE)
        if total == 0 and self._status:
            # Preserve an error/failure status when the list is empty
            return
        source = self._loaded_source or "loading"
        status = (
            f"{total} titles ({source})  |  "
            f"page {self._page + 1}/{total_pages}  |  "
            f"included: {len(self._include)}  excluded: {len(self._exclude)}"
        )
        self._set_status(status)

    def _set_status(self, msg: str) -> None:
        self._status = msg
        try:
            self.query_one("#status-line", Label).update(msg)
        except Exception:
            # defensive: status Label may be unmounted during teardown
            pass

    def _current_title(self) -> str | None:
        table: DataTable = self.query_one("#wantlist-table", DataTable)
        row = table.cursor_row
        start = self._page * self._PAGE_SIZE
        idx = start + row
        if 0 <= idx < len(self._wantlist):
            return self._wantlist[idx]
        return None

    def action_toggle_include(self) -> None:
        title = self._current_title()
        if title is None:
            return
        if title in self._include:
            self._include.discard(title)
        else:
            self._include.add(title)
            self._exclude.discard(title)
        self._render_page()

    def action_toggle_exclude(self) -> None:
        title = self._current_title()
        if title is None:
            return
        if title in self._exclude:
            self._exclude.discard(title)
        else:
            self._exclude.add(title)
            self._include.discard(title)
        self._render_page()

    def action_page_prev(self) -> None:
        if self._page > 0:
            self._page -= 1
            self._render_page()

    def action_page_next(self) -> None:
        total_pages = max(1, (len(self._wantlist) + self._PAGE_SIZE - 1) // self._PAGE_SIZE)
        if self._page < total_pages - 1:
            self._page += 1
            self._render_page()

    def action_refresh(self) -> None:
        """Force a fresh fetch: invalidate cache + re-kick the worker."""
        from retrofetch.wantlist_cache import invalidate
        try:
            cache_dir = self.app.config.cache_dir  # pyright: ignore[reportAttributeAccessIssue]
            invalidate(cache_dir, self.shortname)
        except Exception:
            pass
        self._wantlist = []
        self._loaded_source = ""
        self._page = 0
        self._set_status(f"Refreshing wantlist for {self.shortname}...")
        self._render_page()
        self._kick_load()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_save(self) -> None:
        overrides_path = Path("overrides.yml")
        if not overrides_path.exists():
            # Fall back to the example file as a template; we still save to overrides.yml
            example = Path("overrides.yml.example")
            if example.exists():
                overrides_path.write_bytes(example.read_bytes())
            else:
                overrides_path.write_text("consoles: {}\n", encoding="utf-8")
        raw = _yaml_rt.load(overrides_path.read_text(encoding="utf-8"))
        if raw is None:
            raw = {}
        consoles = raw.get("consoles")
        if consoles is None:
            from ruamel.yaml.comments import CommentedMap  # pyright: ignore[reportMissingImports]
            consoles = CommentedMap()
            raw["consoles"] = consoles
        entry = consoles.get(self.shortname)
        if entry is None:
            from ruamel.yaml.comments import CommentedMap  # pyright: ignore[reportMissingImports]
            entry = CommentedMap()
            consoles[self.shortname] = entry
        entry["include"] = sorted(self._include)
        entry["exclude"] = sorted(self._exclude)
        # Preserve existing limit/region_priority if present - untouched.
        try:
            save_overrides(overrides_path, raw)
            self._set_status(f"saved overrides.yml (include={len(self._include)}, exclude={len(self._exclude)})")
        except Exception as exc:
            self._set_status(f"save failed: {exc}")
