from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

from retrofetch.config import Config
from retrofetch.downloader import DownloadResult
from retrofetch.events import DatLoadDoneEvent, EventBus
from retrofetch.orchestrator import run_console
from retrofetch.sources import DownloadCandidate
from retrofetch.dispatcher import SourceDispatcher
from retrofetch.state import State


class _ConcurrentFakeDispatcher:
    active = 0
    max_active = 0
    lock = threading.Lock()

    def __init__(
        self,
        console_entry: dict[str, Any],
        source_names: list[str],
        allow_torrent: bool,
    ) -> None:
        self.console_entry = console_entry
        self.source_names = source_names
        self.allow_torrent = allow_torrent

    def dispatch_download(
        self,
        *,
        game_title: str,
        game: Any,
        target_dir: Path,
        region_priority: list[str],
        state: State,
        console: str,
        event_bus: EventBus | None = None,
        extract_archives: bool = False,
        verification_available: bool = True,
        state_lock: threading.Lock | None = None,
    ) -> DownloadResult:
        assert state_lock is not None
        with self.lock:
            type(self).active += 1
            type(self).max_active = max(type(self).max_active, type(self).active)
        try:
            time.sleep(0.05)
            return DownloadResult(status="acquired", filename=f"{game_title}.zip")
        finally:
            with self.lock:
                type(self).active -= 1


def test_run_console_uses_bounded_concurrency(monkeypatch, scratch_path) -> None:
    _ConcurrentFakeDispatcher.active = 0
    _ConcurrentFakeDispatcher.max_active = 0
    monkeypatch.setattr(
        "retrofetch.orchestrator.SourceDispatcher",
        _ConcurrentFakeDispatcher,
    )
    config = Config(
        roms_root=scratch_path,
        source_fallback_by_class={"A": ["fake"]},
        max_concurrent_downloads=99,
    )

    report = run_console(
        {"shortname": "fake", "class": "A"},
        [f"Game {idx}" for idx in range(6)],
        config,
        allow_torrent=False,
        consoles_yml={"consoles": [{"shortname": "fake", "class": "A"}]},
    )

    assert report.acquired == 6
    assert 2 <= _ConcurrentFakeDispatcher.max_active <= 3


class _UnverifiedFakeDispatcher:
    def __init__(
        self,
        console_entry: dict[str, Any],
        source_names: list[str],
        allow_torrent: bool,
    ) -> None:
        pass

    def dispatch_download(
        self,
        *,
        game_title: str,
        game: Any,
        target_dir: Path,
        region_priority: list[str],
        state: State,
        console: str,
        event_bus: EventBus | None = None,
        extract_archives: bool = False,
        verification_available: bool = True,
        state_lock: threading.Lock | None = None,
    ) -> DownloadResult:
        assert verification_available is False
        assert state_lock is not None
        return DownloadResult(status="unverified", filename=f"{game_title}.zip")


def test_missing_dat_is_nonfatal_and_reports_unverified(
    monkeypatch, scratch_path
) -> None:
    monkeypatch.setattr(
        "retrofetch.orchestrator.SourceDispatcher",
        _UnverifiedFakeDispatcher,
    )
    events = []
    bus = EventBus()
    bus.subscribe(events.append)
    config = Config(
        roms_root=scratch_path,
        source_fallback_by_class={"A": ["fake"]},
        max_concurrent_downloads=1,
    )

    report = run_console(
        {"shortname": "missingdat", "class": "A"},
        ["Game"],
        config,
        allow_torrent=False,
        consoles_yml={"consoles": [{"shortname": "missingdat", "class": "A"}]},
        event_bus=bus,
    )

    done = [event for event in events if isinstance(event, DatLoadDoneEvent)][0]
    assert done.status == "missing"
    assert done.detail is not None
    assert "not available" in done.detail
    assert report.unverified == 1
    assert report.failed == 0


def test_empty_dat_is_nonfatal_and_reports_unverified(
    monkeypatch, scratch_path
) -> None:
    dat_path = scratch_path / "empty.dat"
    dat_path.write_text("<datafile></datafile>", encoding="utf-8")
    monkeypatch.setattr(
        "retrofetch.orchestrator.SourceDispatcher",
        _UnverifiedFakeDispatcher,
    )
    monkeypatch.setattr(
        "retrofetch.orchestrator.find_dat_for_console",
        lambda shortname, consoles_yml, dats_dir: dat_path,
    )
    events = []
    bus = EventBus()
    bus.subscribe(events.append)
    config = Config(
        roms_root=scratch_path,
        source_fallback_by_class={"A": ["fake"]},
        max_concurrent_downloads=1,
    )

    report = run_console(
        {"shortname": "emptydat", "class": "A"},
        ["Game"],
        config,
        allow_torrent=False,
        consoles_yml={"consoles": [{"shortname": "emptydat", "class": "A"}]},
        event_bus=bus,
    )

    done = [event for event in events if isinstance(event, DatLoadDoneEvent)][0]
    assert done.status == "empty"
    assert done.detail is not None
    assert "0 games" in done.detail
    assert report.unverified == 1
    assert report.failed == 0


class _FoundSource:
    name = "found"

    def __init__(self, entry: dict[str, object]) -> None:
        self.entry = entry

    def find_url_for_game(
        self, title: str, region_priority: list[str] | None = None
    ) -> DownloadCandidate:
        return DownloadCandidate("https://example.invalid/game.zip", "game.zip", self.name)

    def download(self, *args, **kwargs) -> Path:
        raise AssertionError("download_game is monkeypatched")


class _ShouldNotRunSource(_FoundSource):
    name = "fallback"

    def find_url_for_game(
        self, title: str, region_priority: list[str] | None = None
    ) -> DownloadCandidate:
        raise AssertionError("fallback source should not run after unverified success")


def test_dispatcher_treats_unverified_download_as_terminal_success(
    monkeypatch, scratch_path
) -> None:
    import retrofetch.dispatcher as dispatcher_mod

    monkeypatch.setitem(dispatcher_mod._SOURCE_FACTORIES, "found", _FoundSource)
    monkeypatch.setitem(dispatcher_mod._SOURCE_FACTORIES, "fallback", _ShouldNotRunSource)
    monkeypatch.setattr(
        dispatcher_mod,
        "download_game",
        lambda **kwargs: DownloadResult(status="unverified", filename="game.zip"),
    )

    result = SourceDispatcher(
        {"shortname": "fake", "class": "A"},
        ["found", "fallback"],
        allow_torrent=False,
    ).dispatch_download(
        game_title="Game",
        game=None,
        target_dir=scratch_path,
        region_priority=["USA"],
        state=State(console="fake"),
        console="fake",
        verification_available=False,
    )

    assert result.status == "unverified"
    assert result.reason == "found:unverified"
