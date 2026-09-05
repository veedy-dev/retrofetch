from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, ClassVar

import pytest

from retrofetch.config import Config
from retrofetch.dat import DatEntry
from retrofetch.dat import GameEntry as DatGameEntry
from retrofetch.dispatcher import DeferredTorrentAttempt, SourceDispatcher
from retrofetch.downloader import DownloadResult
from retrofetch.events import DatLoadDoneEvent, EventBus
from retrofetch.orchestrator import run_console
from retrofetch.sources import DownloadCandidate
from retrofetch.state import State
from retrofetch.torrent import PreparedTorrent


class _ConcurrentFakeDispatcher:
    active = 0
    created = 0
    max_active = 0
    seen_games: ClassVar[list[Any]] = []
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
        with self.lock:
            type(self).created += 1

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
            type(self).seen_games.append(game)
        try:
            time.sleep(0.05)
            return DownloadResult(status="acquired", filename=f"{game_title}.zip")
        finally:
            with self.lock:
                type(self).active -= 1


def test_run_console_uses_bounded_concurrency(monkeypatch, scratch_path) -> None:
    _ConcurrentFakeDispatcher.active = 0
    _ConcurrentFakeDispatcher.created = 0
    _ConcurrentFakeDispatcher.max_active = 0
    _ConcurrentFakeDispatcher.seen_games = []
    monkeypatch.setattr(
        "retrofetch.orchestrator.SourceDispatcher",
        _ConcurrentFakeDispatcher,
    )
    config = Config(
        roms_root=scratch_path,
        source_fallback_by_class={"A": ["fake"]},
        max_concurrent_downloads=16,
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
    assert _ConcurrentFakeDispatcher.created == _ConcurrentFakeDispatcher.max_active


def test_run_console_reuses_dispatcher_in_serial_mode(
    monkeypatch, scratch_path
) -> None:
    _ConcurrentFakeDispatcher.active = 0
    _ConcurrentFakeDispatcher.created = 0
    _ConcurrentFakeDispatcher.max_active = 0
    _ConcurrentFakeDispatcher.seen_games = []
    monkeypatch.setattr(
        "retrofetch.orchestrator.SourceDispatcher",
        _ConcurrentFakeDispatcher,
    )
    config = Config(
        roms_root=scratch_path,
        source_fallback_by_class={"A": ["fake"]},
        max_concurrent_downloads=1,
    )

    report = run_console(
        {"shortname": "fake", "class": "A"},
        [f"Game {idx}" for idx in range(4)],
        config,
        allow_torrent=False,
        consoles_yml={"consoles": [{"shortname": "fake", "class": "A"}]},
    )

    assert report.acquired == 4
    assert _ConcurrentFakeDispatcher.created == 1


def test_run_console_builds_dat_lookup_once(monkeypatch, scratch_path) -> None:
    dat_games = [
        DatGameEntry(name=f"Game {idx}", description="", category=None)
        for idx in range(50)
    ]
    titles = [f"Game {idx}" for idx in range(40, 50)]
    strip_calls = 0

    from retrofetch import orchestrator as orchestrator_mod

    original_strip_disc_marker = orchestrator_mod.strip_disc_marker

    def counted_strip_disc_marker(title: str) -> str:
        nonlocal strip_calls
        strip_calls += 1
        return original_strip_disc_marker(title)

    _ConcurrentFakeDispatcher.active = 0
    _ConcurrentFakeDispatcher.created = 0
    _ConcurrentFakeDispatcher.max_active = 0
    _ConcurrentFakeDispatcher.seen_games = []
    monkeypatch.setattr(orchestrator_mod, "SourceDispatcher", _ConcurrentFakeDispatcher)
    monkeypatch.setattr(orchestrator_mod, "strip_disc_marker", counted_strip_disc_marker)
    monkeypatch.setattr(
        orchestrator_mod,
        "find_dat_for_console",
        lambda shortname, consoles_yml, dats_dir: scratch_path / "fake.dat",
    )
    monkeypatch.setattr(orchestrator_mod, "parse_dat", lambda path: DatEntry(dat_games))
    config = Config(
        roms_root=scratch_path,
        source_fallback_by_class={"A": ["fake"]},
        max_concurrent_downloads=1,
    )

    report = run_console(
        {"shortname": "fake", "class": "A"},
        titles,
        config,
        allow_torrent=False,
        consoles_yml={"consoles": [{"shortname": "fake", "class": "A"}]},
    )

    assert report.acquired == len(titles)
    assert strip_calls == len(dat_games) + len(titles)
    assert [game.name for game in _ConcurrentFakeDispatcher.seen_games] == titles


def test_pre_cancelled_run_reports_every_item_cancelled(scratch_path) -> None:
    stop = threading.Event()
    stop.set()
    config = Config(
        roms_root=scratch_path,
        source_fallback_by_class={"A": []},
        max_concurrent_downloads=1,
    )

    report = run_console(
        {"shortname": "fake", "class": "A"},
        ["Game A", "Game B"],
        config,
        allow_torrent=False,
        consoles_yml={"consoles": [{"shortname": "fake", "class": "A"}]},
        stop_event=stop,
    )

    assert report.attempted == 2
    assert report.cancelled == 2
    assert report.acquired + report.failed + report.skipped + report.cancelled == 2


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

    done = next(event for event in events if isinstance(event, DatLoadDoneEvent))
    assert done.status == "missing"
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

    done = next(event for event in events if isinstance(event, DatLoadDoneEvent))
    assert done.status == "empty"
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


class _GroupedFakeCoordinator:
    batches: ClassVar[list[list[str]]] = []

    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    def transfer_many(self, items, **kwargs):
        type(self).batches.append([item.item_id for item in items])
        return {
            item.item_id: PreparedTorrent(
                item.target_dir / f"{item.item_id}.part",
                item.target_dir,
            )
            for item in items
        }

    def close(self) -> None:
        pass


class _GroupedFakeDispatcher:
    def __init__(
        self,
        console_entry: dict[str, Any],
        source_names: list[str],
        allow_torrent: bool,
    ) -> None:
        self.torrent_coordinator = None

    def dispatch_until_torrent(self, *, game_title: str, **kwargs):
        candidate = DownloadCandidate(
            "https://example.test/collection.torrent",
            f"{game_title}.zip",
            "minerva_torrent",
            expected_size=1,
            extra={
                "transport": "torrent",
                "torrent_url": "https://example.test/collection.torrent",
                "torrent_infohash": "a" * 40,
                "torrent_internal_path": f"Collection/{game_title}.zip",
                "torrent_file_index": 0 if game_title == "Game A" else 1,
                "torrent_name": "Collection",
            },
        )
        return DeferredTorrentAttempt(
            source_index=0,
            source_name="minerva_torrent",
            candidate=candidate,
            attempts_summary=(),
            item_id=game_title,
        )

    def resume_download(self, deferred, *, prepared, transfer_error, **kwargs):
        assert prepared is not None
        assert transfer_error is None
        return DownloadResult(status="unverified", filename=deferred.candidate.filename)


@pytest.mark.parametrize("workers", [1, 3])
def test_run_console_batches_same_infohash_after_workers_drain(
    monkeypatch: pytest.MonkeyPatch,
    scratch_path: Path,
    workers: int,
) -> None:
    _GroupedFakeCoordinator.batches = []
    monkeypatch.setattr(
        "retrofetch.orchestrator.SourceDispatcher", _GroupedFakeDispatcher
    )
    monkeypatch.setattr(
        "retrofetch.orchestrator.TorrentCoordinator", _GroupedFakeCoordinator
    )
    config = Config(
        roms_root=scratch_path,
        source_fallback_by_class={"A": ["minerva_torrent"]},
        max_concurrent_downloads=workers,
    )

    report = run_console(
        {"shortname": "fake", "class": "A"},
        ["Game A", "Game B"],
        config,
        allow_torrent=True,
        consoles_yml={"consoles": [{"shortname": "fake", "class": "A"}]},
    )

    assert len(_GroupedFakeCoordinator.batches) == 1
    assert sorted(_GroupedFakeCoordinator.batches[0]) == ["Game A", "Game B"]
    assert report.attempted == 2
    assert report.unverified == 2
    assert report.failed == 0
