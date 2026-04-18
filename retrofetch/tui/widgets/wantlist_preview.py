"""Live wantlist preview widget for the Home main panel.

Display-only. All fetch logic lives in HomeScreen; this widget owns text layout.
Four display modes: IDLE, LOADING, READY, FAILED. Action hints always visible.

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


_HINTS = "[w] wantlist  [d] download  [s] state  [C] coverage  [?] help  [q] quit"


class WantlistPreview(Static):
    """Main-panel widget mirroring the currently highlighted console's wantlist state.

    Display-only. Public API:
    - show_idle()
    - show_loading(console)
    - show_ready(console, titles, from_cache, state_counts)
    - show_failed(console, reason)
    """

    state: reactive[PreviewState] = reactive("IDLE")

    def on_mount(self) -> None:
        self.show_idle()

    def _set_body(self, body: str) -> None:
        # Text() bypasses Rich markup so ``[w]`` etc. render as literal brackets.
        self.update(Text(body))

    def show_idle(self) -> None:
        self.state = "IDLE"
        self._set_body(f"Select a console from the sidebar.\n\n{_HINTS}")

    def show_loading(self, console: str) -> None:
        self.state = "LOADING"
        self._set_body(f"Fetching wantlist for {console}...\n\n{_HINTS}")

    def show_ready(
        self,
        console: str,
        titles: list[str],
        from_cache: bool,
        state_counts: dict[str, int],
    ) -> None:
        self.state = "READY"
        indicator = "cached" if from_cache else "fresh"
        count = len(titles)
        header = f"{console} - {count} titles ({indicator})"
        top = titles[:20]
        if top:
            listing = "\n".join(f"  {i + 1:>2}. {title}" for i, title in enumerate(top))
        else:
            listing = "  (empty wantlist)"
        if count > 20:
            listing += f"\n  ... ({count - 20} more)"
        acquired = state_counts.get("acquired", 0)
        failed = state_counts.get("failed", 0)
        pending = state_counts.get("pending", 0)
        counts_line = f"state: acquired={acquired}  failed={failed}  pending={pending}"
        body = "\n".join([header, "", listing, "", counts_line, "", _HINTS])
        self._set_body(body)

    def show_failed(self, console: str, reason: str) -> None:
        self.state = "FAILED"
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
