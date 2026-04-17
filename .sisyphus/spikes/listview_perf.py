from __future__ import annotations

import asyncio
from importlib import import_module
import pathlib
import time
from dataclasses import dataclass

import yaml

_textual_app = import_module("textual.app")
_textual_widgets = import_module("textual.widgets")

App = _textual_app.App
ComposeResult = _textual_app.ComposeResult
Input = _textual_widgets.Input
Label = _textual_widgets.Label
ListItem = _textual_widgets.ListItem
ListView = _textual_widgets.ListView

CONSOLES_PATH = pathlib.Path("consoles.yml")
EXPECTED_CONSOLES = 178
FILTER_QUERIES = ["ne", "a", "zzz", "nintendo", ""]
DEBOUNCE_VALUES = [0, 50, 100, 200]


@dataclass(frozen=True)
class FilterResult:
    query: str
    count: int
    elapsed_ms: float


class ConsoleListApp(App[None]):
    CSS = """
    Input {
        dock: top;
    }

    ListView {
        height: 1fr;
    }
    """

    def __init__(self, consoles: list[dict[str, object]], debounce_ms: int = 0) -> None:
        super().__init__()
        self._consoles = consoles
        self._debounce_s = debounce_ms / 1000
        self._pending_timer = None
        self._entries: list[tuple[str, ListItem]] = []
        self.filter_calls = 0
        self.applied_query = ""
        self.last_visible_count = 0

    def compose(self) -> ComposeResult:
        yield Input(placeholder="filter consoles...")
        items: list[tuple[str, ListItem]] = []
        for console in self._consoles:
            display_name = str(console["display_name"])
            items.append((display_name, ListItem(Label(display_name))))
        self._entries = items
        yield ListView(*(item for _, item in items))

    def on_mount(self) -> None:
        self.query_one(Input).focus()
        self._apply_filter()

    def on_input_changed(self, message: Input.Changed) -> None:
        if self._pending_timer is not None:
            self._pending_timer.stop()
            self._pending_timer = None
        if self._debounce_s <= 0:
            self._apply_filter()
            return
        self._pending_timer = self.set_timer(self._debounce_s, self._apply_filter)

    def _apply_filter(self) -> None:
        query = self.query_one(Input).value.lower()
        self.applied_query = query
        self.filter_calls += 1
        visible = 0
        for display_name, item in self._entries:
            should_show = query in display_name.lower()
            item.display = should_show
            if should_show:
                visible += 1
        self.last_visible_count = visible


def load_consoles() -> list[dict[str, object]]:
    data = yaml.safe_load(CONSOLES_PATH.read_text(encoding="utf-8"))
    consoles = data["consoles"]
    if len(consoles) != EXPECTED_CONSOLES:
        raise ValueError(f"expected {EXPECTED_CONSOLES} consoles, got {len(consoles)}")
    return consoles


def expected_count(consoles: list[dict[str, object]], query: str) -> int:
    lowered = query.lower()
    return sum(1 for console in consoles if lowered in str(console["display_name"]).lower())


async def wait_for_count(
    app: ConsoleListApp,
    pilot,
    target_count: int,
    expected_query: str,
    timeout_s: float = 5.0,
    pause_s: float = 0.02,
) -> float:
    start = time.perf_counter()
    last_count = None
    stable_hits = 0
    while time.perf_counter() - start < timeout_s:
        await pilot.pause(pause_s)
        current_count = app.last_visible_count
        if (
            current_count == target_count
            and current_count == last_count
            and app.applied_query == expected_query
        ):
            stable_hits += 1
            if stable_hits >= 1:
                return (time.perf_counter() - start) * 1000
        else:
            stable_hits = 0
        last_count = current_count
    raise TimeoutError(f"timed out waiting for count {target_count} for {expected_query!r}")


async def measure_filter_latencies(consoles: list[dict[str, object]]) -> list[FilterResult]:
    app = ConsoleListApp(consoles, debounce_ms=0)
    results: list[FilterResult] = []
    async with app.run_test() as pilot:
        await wait_for_count(app, pilot, EXPECTED_CONSOLES, "")
        input_widget = app.query_one(Input)
        list_view = app.query_one(ListView)
        for query in FILTER_QUERIES:
            target_count = expected_count(consoles, query)
            input_widget.focus()
            input_widget.value = query
            elapsed_ms = await wait_for_count(app, pilot, target_count, query)
            results.append(
                FilterResult(
                    query=query,
                    count=sum(1 for child in list_view.children if child.display),
                    elapsed_ms=elapsed_ms,
                )
            )
    return results


async def measure_debounce(consoles: list[dict[str, object]], debounce_ms: int) -> tuple[float, int, int]:
    app = ConsoleListApp(consoles, debounce_ms=debounce_ms)
    async with app.run_test() as pilot:
        await wait_for_count(app, pilot, EXPECTED_CONSOLES, "")
        input_widget = app.query_one(Input)
        input_widget.focus()
        before_calls = app.filter_calls
        start = time.perf_counter()
        input_widget.value = ""
        await pilot.pause(0.02)
        for char in "nintendo":
            await pilot.press(char)
            await pilot.pause(0.01)
        expected = expected_count(consoles, "nintendo")
        elapsed_ms = await wait_for_count(app, pilot, expected, "nintendo", timeout_s=8.0, pause_s=0.02)
        total_ms = (time.perf_counter() - start) * 1000 if elapsed_ms is None else elapsed_ms
        return total_ms, app.filter_calls - before_calls, expected


async def main() -> int:
    try:
        consoles = load_consoles()
        initial_app = ConsoleListApp(consoles, debounce_ms=0)
        async with initial_app.run_test() as pilot:
            initial_ms = await wait_for_count(initial_app, pilot, EXPECTED_CONSOLES, "")
        filter_results = await measure_filter_latencies(consoles)
        debounce_results: list[tuple[int, float, int, int]] = []
        for debounce_ms in DEBOUNCE_VALUES:
            total_ms, filter_calls, final_count = await measure_debounce(consoles, debounce_ms)
            debounce_results.append((debounce_ms, total_ms, filter_calls, final_count))
        recommended = None
        for debounce_ms, total_ms, filter_calls, _ in debounce_results:
            if total_ms <= 500 and filter_calls == 1:
                recommended = debounce_ms
                break
        print(f"loaded consoles: {len(consoles)}")
        print(f"initial render: {initial_ms:.2f}ms")
        for result in filter_results:
            print(f"filter query={result.query!r} count={result.count} time={result.elapsed_ms:.2f}ms")
        for debounce_ms, total_ms, filter_calls, final_count in debounce_results:
            print(
                f"debounce {debounce_ms}ms total={total_ms:.2f}ms filter_calls={filter_calls} final_count={final_count}"
            )
        if recommended is None:
            print("VERDICT: NO-GO reason=no debounce value met the <=500ms and single-filter-call heuristic")
        else:
            print(f"recommended debounce: {recommended}ms")
            print(f"VERDICT: GO, debounce={recommended}ms")
        return 0
    except Exception as error:
        print(f"VERDICT: NO-GO reason={error}")
        return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
