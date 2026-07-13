"""Live wantlist preview widget for the Home main panel.

Display-only. All fetch logic lives in HomeScreen; this widget owns text layout.
Four display modes: IDLE, LOADING, READY, FAILED. Action hints always visible.

Pagination: the widget accepts the FULL title list from the cache layer and
renders `PAGE_SIZE` titles per page. Use `next_page()` / `prev_page()` to move
through pages (no-op on IDLE/LOADING/FAILED or when only one page exists).

Markup note: action hints contain ``[w]``/``[d]``/etc. which Textual/Rich would
otherwise treat as style tags. We render via ``rich.text.Text`` so brackets
stay literal.
"""

from __future__ import annotations

from typing import Literal

from rich.text import Text
from textual.reactive import reactive  # pyright: ignore[reportMissingImports]
from textual.widgets import Static  # pyright: ignore[reportMissingImports]


PreviewState = Literal["IDLE", "LOADING", "READY", "FAILED"]


_HINTS = "[g] select games  [d] download  [,] settings  [s] state  [?] help  [q] quit"

_IDLE_BODY = (
    "Select a console from the sidebar.\n"
    "\n"
    "Sidebar color legend:\n"
    "  green    has a ranking provider (you can browse games)\n"
    "  grey     no provider - skipped or unsupported\n"
    "\n"
    f"{_HINTS}"
)


class WantlistPreview(Static):
    """Main-panel widget mirroring the currently highlighted console's wantlist state.

    Display-only. Public API:
    - show_idle()
    - show_loading(console)
    - show_ready(console, titles, state_counts)
    - show_failed(console, reason)
    - next_page() / prev_page()
    """

    PAGE_SIZE = 20

    state: reactive[PreviewState] = reactive("IDLE")

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._titles: list[str] = []
        self._page: int = 0
        # Textual's Widget reserves `_console`; use a different name to avoid
        # the "property has no setter" crash on construction.
        self._current_console: str = ""
        self._counts: dict[str, int] = {}

    def on_mount(self) -> None:
        self.show_idle()

    # -- internal helpers --------------------------------------------------

    def _set_body(self, body: str) -> None:
        # Text() bypasses Rich markup so ``[w]`` etc. render as literal brackets.
        self.update(Text(body))

    def _total_pages(self) -> int:
        if not self._titles:
            return 1
        return (len(self._titles) + self.PAGE_SIZE - 1) // self.PAGE_SIZE

    def _reset_state(self) -> None:
        self._titles = []
        self._page = 0
        self._current_console = ""
        self._counts = {}

    def _render_current_page(self) -> None:
        total = len(self._titles)
        total_pages = self._total_pages()
        header = f"{self._current_console} - {total} titles"

        start = self._page * self.PAGE_SIZE
        end = start + self.PAGE_SIZE
        page_titles = self._titles[start:end]

        if page_titles:
            listing = "\n".join(
                f"  {start + i + 1:>3}. {title}" for i, title in enumerate(page_titles)
            )
        else:
            listing = "  (no games found)"

        acquired = self._counts.get("acquired", 0)
        failed = self._counts.get("failed", 0)
        pending = self._counts.get("pending", 0)
        counts_line = f"state: acquired={acquired}  failed={failed}  pending={pending}"

        lines = [header, "", listing, "", counts_line, ""]
        if total_pages > 1:
            lines.append(f"Page {self._page + 1}/{total_pages}    <- prev    -> next")
            lines.append("")
        lines.append(_HINTS)
        self._set_body("\n".join(lines))

    # -- public API --------------------------------------------------------

    def show_idle(self) -> None:
        self.loading = False
        self._reset_state()
        self.state = "IDLE"
        self._set_body(_IDLE_BODY)

    def show_loading(self, console: str) -> None:
        self._reset_state()
        self.state = "LOADING"
        self._current_console = console
        self._set_body(f"Fetching games for {console}...\n\n{_HINTS}")
        self.loading = True

    def show_ready(
        self,
        console: str,
        titles: list[str],
        state_counts: dict[str, int],
    ) -> None:
        self.loading = False
        self.state = "READY"
        self._current_console = console
        self._titles = list(titles)
        self._counts = dict(state_counts)
        self._page = 0
        self._render_current_page()

    def show_failed(self, console: str, reason: str) -> None:
        self.loading = False
        self._reset_state()
        self.state = "FAILED"
        self._current_console = console
        body = "\n".join(
            [
                f"Fetch failed for {console}: {reason}",
                "",
                "[R] Retry (Ctrl+R)",
                "",
                _HINTS,
            ]
        )
        self._set_body(body)

    def next_page(self) -> None:
        if self.state != "READY":
            return
        if self._page + 1 >= self._total_pages():
            return
        self._page += 1
        self._render_current_page()

    def prev_page(self) -> None:
        if self.state != "READY":
            return
        if self._page <= 0:
            return
        self._page -= 1
        self._render_current_page()
