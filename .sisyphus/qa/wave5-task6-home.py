"""U6 home screen Pilot scenarios: debounce, cache-hit, retry.

Writes three evidence files (one per scenario) and prints one OK line per
scenario. Exits 1 on first failure.
"""
from __future__ import annotations

import asyncio
import importlib
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from retrofetch.config import Config, _yaml_rt
from retrofetch.tui.app import RetrofetchApp
from retrofetch.tui.screens.home import HomeScreen
from retrofetch.tui.widgets.wantlist_preview import WantlistPreview
from retrofetch.wantlist_cache import CachedWantlist, cache_path, save_cached


REPO_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_DIR = REPO_ROOT / ".sisyphus" / "evidence"


def _write_evidence(slug: str, text: str) -> None:
    # Absolute path so chdir(td) in scenarios still writes to the real repo.
    p = EVIDENCE_DIR / f"ux-task-6-{slug}.txt"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _load_consoles() -> dict:
    repo_root = Path(__file__).resolve().parents[2]
    consoles_path = repo_root / "consoles.yml"
    return _yaml_rt.load(consoles_path.read_text(encoding="utf-8"))


async def scenario_debounce() -> None:
    """Rapid highlight of 3 consoles within debounce window → worker runs once."""
    consoles_yml = _load_consoles()
    cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td).resolve()
        os.chdir(td)
        try:
            config = Config(roms_root=td_path / "ROMs", cache_dir=td_path / "cache")
            app = RetrofetchApp(
                config=config,
                config_path=Path("config.yml"),
                consoles_yml=consoles_yml,
                overrides={},
                first_run=False,
            )

            # Install counting monkey-patch at the home-module import site.
            import retrofetch.tui.screens.home as home_mod
            calls: list[str] = []

            def fake_get_or_fetch(console_entry, overrides, config, limit):
                calls.append(str(console_entry.get("shortname", "")))
                return (["Alpha", "Beta", "Gamma"], False)

            # Instrument the handler so we can see if it's being triggered.
            highlight_hits: list[str] = []
            _orig_handler = home_mod.HomeScreen.on_list_view_highlighted

            def _instrumented(self, event):
                item = event.item
                klass = getattr(item, "_rf_klass", "?") if item else None
                short = getattr(item, "_rf_shortname", "?") if item else None
                highlight_hits.append(f"{klass}:{short}")
                return _orig_handler(self, event)

            original = home_mod.get_or_fetch_wantlist
            home_mod.get_or_fetch_wantlist = fake_get_or_fetch
            home_mod.HomeScreen.on_list_view_highlighted = _instrumented
            last_shortname = ""
            try:
                async with app.run_test() as pilot:
                    await pilot.pause(0.3)
                    list_view = app.screen.query_one("#console-list")
                    # Pick 3 class A/B/C indices (rapid-fire highlight changes)
                    eligible = [
                        i for i, (e, _) in enumerate(app.screen._all_items)
                        if str(e.get("class", "")) in ("A", "B", "C")
                    ]
                    assert len(eligible) >= 3, f"not enough A/B/C consoles: {len(eligible)}"
                    # Remember the shortname we expect to see fetched
                    last_shortname = str(app.screen._all_items[eligible[2]][0].get("shortname", ""))
                    # Rapidly change the highlighted index within the debounce window
                    list_view.index = eligible[0]
                    list_view.index = eligible[1]
                    list_view.index = eligible[2]
                    # Wait for debounce timer (400ms) + worker completion
                    await pilot.pause(1.5)
                    app.exit(0)

                # Assert exactly ONE fetch ran (debounce absorbed the first two).
                assert len(calls) == 1, (
                    f"expected 1 fetch, got {len(calls)}: calls={calls} hits={highlight_hits}"
                )
                assert calls[0] == last_shortname, (
                    f"expected fetch for last highlighted {last_shortname!r}, got {calls[0]!r}"
                )
                _write_evidence(
                    "debounce",
                    f"status=PASS\ncalls={calls}\nfetch_count={len(calls)}\nhighlight_hits={highlight_hits}\n",
                )
                print(f"OK: debounced auto-fetch (1 call for {len(highlight_hits)} highlights)")
            finally:
                home_mod.HomeScreen.on_list_view_highlighted = _orig_handler
                home_mod.get_or_fetch_wantlist = original
        finally:
            os.chdir(cwd)


async def scenario_cache_hit() -> None:
    """Pre-seeded cache → highlight triggers no worker, preview shows cached."""
    consoles_yml = _load_consoles()
    cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td).resolve()
        os.chdir(td)
        try:
            cache_dir = td_path / "cache"
            config = Config(roms_root=td_path / "ROMs", cache_dir=cache_dir)

            # Pick first class A console (typically nes)
            entries = consoles_yml.get("consoles", []) or []
            target = next(
                (e for e in entries if str(e.get("class", "")) == "A"),
                None,
            )
            assert target is not None, "consoles.yml has no class A console"
            shortname = str(target["shortname"])

            # Seed cache
            save_cached(
                cache_dir,
                CachedWantlist(
                    console=shortname,
                    titles=["Cached Title 1", "Cached Title 2"],
                    cached_at=datetime.now(timezone.utc),
                    ttl_hours=24,
                ),
            )
            assert cache_path(cache_dir, shortname).exists()

            app = RetrofetchApp(
                config=config,
                config_path=Path("config.yml"),
                consoles_yml=consoles_yml,
                overrides={},
                first_run=False,
            )

            import retrofetch.tui.screens.home as home_mod
            calls: list[str] = []

            def fake_get_or_fetch(console_entry, overrides, config, limit):
                calls.append(str(console_entry.get("shortname", "")))
                return ([], False)

            original = home_mod.get_or_fetch_wantlist
            home_mod.get_or_fetch_wantlist = fake_get_or_fetch
            try:
                async with app.run_test() as pilot:
                    await pilot.pause(0.3)
                    list_view = app.screen.query_one("#console-list")
                    # Find the index of our target in the populated list
                    index = next(
                        (i for i, (e, _) in enumerate(app.screen._all_items) if str(e.get("shortname")) == shortname),
                        0,
                    )
                    # Move cursor to that index (triggers Highlighted events)
                    for _ in range(index + 1):
                        list_view.action_cursor_down()
                    await pilot.pause(0.6)

                    preview = app.screen.query_one("#main-panel", WantlistPreview)
                    state = preview.state
                    app.exit(0)

                # Cache fast-path should short-circuit worker entirely
                assert calls == [], f"worker should not run on cache hit, got {calls}"
                assert state == "READY", f"preview state should be READY, got {state}"
                _write_evidence(
                    "cache-hit",
                    f"status=PASS\nshortname={shortname}\nworker_calls={calls}\npreview_state={state}\n",
                )
                print(f"OK: cache hit for {shortname} skips worker (preview={state})")
            finally:
                home_mod.get_or_fetch_wantlist = original
        finally:
            os.chdir(cwd)


async def scenario_retry() -> None:
    """First fetch raises, Ctrl+R invalidates + re-fetch, second succeeds."""
    consoles_yml = _load_consoles()
    cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td).resolve()
        os.chdir(td)
        try:
            cache_dir = td_path / "cache"
            config = Config(roms_root=td_path / "ROMs", cache_dir=cache_dir)

            entries = consoles_yml.get("consoles", []) or []
            target = next(
                (e for e in entries if str(e.get("class", "")) == "A"),
                None,
            )
            assert target is not None
            shortname = str(target["shortname"])

            app = RetrofetchApp(
                config=config,
                config_path=Path("config.yml"),
                consoles_yml=consoles_yml,
                overrides={},
                first_run=False,
            )

            import retrofetch.tui.screens.home as home_mod
            call_count = {"n": 0}

            def fake_get_or_fetch(console_entry, overrides, config, limit):
                call_count["n"] += 1
                if call_count["n"] == 1:
                    raise RuntimeError("simulated network failure")
                return (["Retry Succeeded Title"], False)

            original = home_mod.get_or_fetch_wantlist
            home_mod.get_or_fetch_wantlist = fake_get_or_fetch
            try:
                async with app.run_test() as pilot:
                    await pilot.pause(0.3)
                    list_view = app.screen.query_one("#console-list")
                    index = next(
                        (i for i, (e, _) in enumerate(app.screen._all_items) if str(e.get("shortname")) == shortname),
                        0,
                    )
                    for _ in range(index + 1):
                        list_view.action_cursor_down()
                    # Wait for debounce + worker + failed message
                    await pilot.pause(1.5)

                    preview = app.screen.query_one("#main-panel", WantlistPreview)
                    state_after_fail = preview.state

                    # Invoke retry action directly (Ctrl+R binding calls action_retry_fetch)
                    app.screen.action_retry_fetch()
                    await pilot.pause(1.5)
                    state_after_retry = preview.state

                    app.exit(0)

                assert state_after_fail == "FAILED", f"expected FAILED after simulated error, got {state_after_fail}"
                assert state_after_retry == "READY", f"expected READY after retry, got {state_after_retry}"
                assert call_count["n"] == 2, f"expected 2 fetch calls (fail + retry), got {call_count['n']}"
                _write_evidence(
                    "retry",
                    "\n".join(
                        [
                            "status=PASS",
                            f"shortname={shortname}",
                            f"state_after_fail={state_after_fail}",
                            f"state_after_retry={state_after_retry}",
                            f"fetch_call_count={call_count['n']}",
                        ]
                    ),
                )
                print("OK: Ctrl+R retry FAILED -> READY after failure")
            finally:
                home_mod.get_or_fetch_wantlist = original
        finally:
            os.chdir(cwd)


async def main() -> None:
    await scenario_debounce()
    await scenario_cache_hit()
    await scenario_retry()
    print("U6 all scenarios passed")


if __name__ == "__main__":
    import traceback
    try:
        asyncio.run(main())
    except AssertionError as exc:
        print(f"FAIL: {exc!r}", file=sys.stderr)
        traceback.print_exc()
        raise SystemExit(1)
