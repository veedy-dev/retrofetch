from __future__ import annotations

import asyncio
import time
from importlib import import_module
from string import ascii_lowercase

textual_app = import_module("textual.app")
textual_widgets = import_module("textual.widgets")
App = textual_app.App
ComposeResult = textual_app.ComposeResult
DataTable = textual_widgets.DataTable
Input = textual_widgets.Input

TOTAL_ROWS = 5000
COLUMNS = ("title", "region", "status", "size", "source")
REGIONS = ("JP", "US", "EU", "KR", "WW")
STATUSES = ("verified", "patched", "demo", "full", "proto")
SIZES = ("256 MB", "512 MB", "768 MB", "1.0 GB", "1.5 GB")
SOURCES = ("archive", "mirror", "cart", "dump", "catalog")
LETTERS = ascii_lowercase


def synthetic_rows() -> list[tuple[str, str, str, str, str]]:
    rows: list[tuple[str, str, str, str, str]] = []
    for index in range(TOTAL_ROWS):
        suffix = f"{LETTERS[index % 26]}{LETTERS[(index // 26) % 26]}"
        rows.append(
            (
                f"Game {index:04d} {suffix}",
                REGIONS[index % len(REGIONS)],
                STATUSES[index % len(STATUSES)],
                SIZES[index % len(SIZES)],
                SOURCES[index % len(SOURCES)],
            )
        )
    return rows


class PerfApp(App[None]):
    def compose(self) -> ComposeResult:
        yield Input(placeholder="filter")
        yield DataTable()

    def on_mount(self) -> None:
        self._rows = synthetic_rows()
        self._table = self.query_one(DataTable)
        self._input = self.query_one(Input)
        self._table.add_columns(*COLUMNS)
        start = time.perf_counter()
        self._populate(self._rows)
        self.initial_ms = (time.perf_counter() - start) * 1000
        self._input.focus()

    def _populate(self, rows: list[tuple[str, str, str, str, str]]) -> None:
        self._table.clear()
        self._table.add_rows(rows)
        self.visible_row_count = len(rows)

    def on_input_changed(self, event: Input.Changed) -> None:
        query = event.value.casefold().strip()
        if query:
            rows = [row for row in self._rows if query in " ".join(row).casefold()]
        else:
            rows = self._rows
        self._populate(rows)


async def run_bench() -> None:
    app = PerfApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one(DataTable)
        table.focus()
        scroll_start = time.perf_counter()
        for _ in range(100):
            await pilot.press("down")
        scroll_ms_avg = (time.perf_counter() - scroll_start) * 10
        app.query_one(Input).focus()
        filter_start = time.perf_counter()
        await pilot.press("a")
        await pilot.press("b")
        filter_ms = (time.perf_counter() - filter_start) * 1000
    print(f"initial_ms={app.initial_ms:.1f}")
    print(f"scroll_ms_avg={scroll_ms_avg:.1f}")
    print(f"filter_ms={filter_ms:.1f}")
    failed = []
    if app.initial_ms >= 500:
        failed.append(f"initial>=500ms ({app.initial_ms:.1f}ms)")
    if scroll_ms_avg >= 100:
        failed.append(f"scroll>=100ms ({scroll_ms_avg:.1f}ms)")
    if filter_ms >= 200:
        failed.append(f"filter>=200ms ({filter_ms:.1f}ms)")
    if failed:
        print("VERDICT: NO-GO " + "; ".join(failed))
    else:
        print("VERDICT: GO")


if __name__ == "__main__":
    asyncio.run(run_bench())
