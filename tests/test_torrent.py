from __future__ import annotations

import hashlib
import os
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

import retrofetch.torrent as torrent_module
from retrofetch.config import Config
from retrofetch.dispatcher import SourceDispatcher
from retrofetch.events import (
    EventBus,
    GameBytesEvent,
    GameCancelledEvent,
    GameStageEvent,
)
from retrofetch.qbittorrent import (
    AddResult,
    ManagedPaths,
    TorrentMetadata,
    TorrentMetadataFile,
)
from retrofetch.sources import DownloadCancelled, DownloadCandidate, SourceUnavailable
from retrofetch.state import GameEntry, State
from retrofetch.torrent import (
    PreparedTorrent,
    TorrentBatchItem,
    TorrentCoordinator,
    TorrentTransferSource,
)
from retrofetch.tui.workers.download_worker import TorrentSetupGate

INFOHASH = "a23ee47c4235d9109ce93c0742d41dbd5f5117d5"
INTERNAL = "Redump/Sony - PlayStation Portable/Game (USA).zip"
QBITTORRENT_INTERNAL = f"PSP collection/{INTERNAL}"
PAYLOAD = b"actual game fixture"
INTERNAL_2 = "Redump/Sony - PlayStation Portable/Game Two (USA).zip"
QBITTORRENT_INTERNAL_2 = f"PSP collection/{INTERNAL_2}"
PAYLOAD_2 = b"second game fixture"


@pytest.mark.skipif(os.name != "nt", reason="Windows managed runtime only")
def test_windows_process_identity_uses_real_process_start_time() -> None:
    from retrofetch.torrent import _windows_process_identity

    executable, launch_time = _windows_process_identity(os.getpid())

    assert executable.is_file()
    assert executable.name.casefold() == "python.exe"
    assert launch_time > 0


def _candidate() -> DownloadCandidate:
    return DownloadCandidate(
        "https://provider.test/collection.torrent",
        "Game (USA).zip",
        "minerva_torrent",
        expected_size=len(PAYLOAD),
        extra={
            "transport": "torrent",
            "torrent_url": "https://provider.test/collection.torrent",
            "torrent_infohash": INFOHASH,
            "torrent_internal_path": INTERNAL,
            "torrent_file_index": 1,
            "torrent_name": "PSP collection",
        },
    )


def _candidate_two() -> DownloadCandidate:
    return DownloadCandidate(
        "https://provider.test/collection.torrent",
        "Game Two (USA).zip",
        "minerva_torrent",
        expected_size=len(PAYLOAD_2),
        extra={
            "transport": "torrent",
            "torrent_url": "https://provider.test/collection.torrent",
            "torrent_infohash": INFOHASH,
            "torrent_internal_path": INTERNAL_2,
            "torrent_file_index": 2,
            "torrent_name": "PSP collection",
        },
    )


class _TorrentSource:
    name = "minerva_torrent"

    def __init__(self, _entry: dict[str, object], enabled: bool = True) -> None:
        pass

    def find_url_for_game(self, title: str, region_priority=None) -> DownloadCandidate:
        return _candidate()

    def download(self, candidate, dest_dir, *, event_bus=None):
        raise AssertionError("resolver must not transfer payloads")


class _FakeClient:
    def __init__(
        self,
        *,
        complete: bool = True,
        owned: bool = True,
        selected_collision: bool = False,
    ) -> None:
        self.complete = complete
        self.owned = owned
        self.added = False
        self.added_source: str | None = None
        self.started = False
        self.stopped = False
        self.deleted = False
        self.closed = False
        self.shutdown_called = False
        self.share_limits_set = False
        self.stage_root: Path | None = None
        self.tag = f"retrofetch-{INFOHASH[:16]}"
        self.job_id = INFOHASH
        self.priorities: list[int] = []
        self.selected_collision = selected_collision

    def fetch_metadata(self, source: str) -> TorrentMetadata:
        files = [
            TorrentMetadataFile(0, "PSP collection/unwanted.bin", 3),
            TorrentMetadataFile(1, QBITTORRENT_INTERNAL, len(PAYLOAD)),
        ]
        if self.selected_collision:
            files.append(
                TorrentMetadataFile(2, QBITTORRENT_INTERNAL.lower(), len(PAYLOAD))
            )
        return TorrentMetadata(
            torrent_id=self.job_id,
            infohash_v1=INFOHASH,
            infohash_v2=None,
            name="PSP collection",
            files=tuple(files),
            total_size=sum(file.length for file in files),
        )

    def parse_metadata(
        self, content: bytes, *, filename: str = "metadata.torrent"
    ) -> TorrentMetadata:
        return self.fetch_metadata(filename)

    def assert_ready(self) -> None:
        return None

    def preferences(self) -> dict[str, object]:
        return {
            "web_ui_address": "127.0.0.1",
            "web_ui_upnp": False,
            "upnp": False,
            "bypass_local_auth": False,
        }

    def process_launch_time(self) -> int:
        return 1_725_000_000

    def add(
        self,
        source: str,
        *,
        file_priorities,
        save_path: Path,
        tag: str,
        stopped: bool = True,
    ) -> AddResult:
        self.added = True
        self.added_source = source
        self.stage_root = save_path
        self.tag = tag
        self.priorities = list(file_priorities)
        return AddResult((self.job_id,), 1, 0, 0)

    def info(self, torrent_id: str | None = None, *, tag: str | None = None):
        if self.deleted or (not self.added and self.owned):
            return ()
        if not self.added and not self.owned:
            self.stage_root = Path("C:/someone-else")
        assert self.stage_root is not None
        return (
            {
                "hash": self.job_id,
                "tags": self.tag if self.owned else "someone-else",
                "save_path": str(self.stage_root),
                "content_path": str(self.stage_root / "PSP collection"),
                "state": "stoppedDL" if self.stopped else "downloading",
                "dlspeed": 1,
                "num_seeds": 1,
                "ratio_limit": 0 if self.share_limits_set else -1,
                "seeding_time_limit": 0 if self.share_limits_set else -1,
                "inactive_seeding_time_limit": 0 if self.share_limits_set else -1,
                "share_limit_action": "Stop" if self.share_limits_set else "Default",
            },
        )

    def files(
        self, torrent_id: str, *, indexes=None
    ) -> tuple[dict[str, object], ...]:
        progress = 1.0 if self.started and self.complete else 0.0
        files = (
            {
                "index": 0,
                "name": "PSP collection/unwanted.bin",
                "size": 3,
                "progress": 0.0,
                "priority": self.priorities[0],
            },
            {
                "index": 1,
                "name": QBITTORRENT_INTERNAL,
                "size": len(PAYLOAD),
                "progress": progress,
                "priority": self.priorities[1],
            },
        )
        if indexes is None:
            return files
        selected = set(indexes)
        return tuple(entry for entry in files if entry["index"] in selected)

    def set_file_priority(self, torrent_id: str, indexes, priority: int) -> None:
        values = [indexes] if isinstance(indexes, int) else indexes
        for index in values:
            self.priorities[index] = priority

    def set_share_limits(self, torrent_id: str) -> None:
        self.share_limits_set = True

    def start(self, torrent_id: str) -> None:
        self.started = True
        self.stopped = False
        assert self.stage_root is not None
        output = self.stage_root / QBITTORRENT_INTERNAL
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(PAYLOAD)

    def stop(self, torrent_id: str) -> None:
        self.stopped = True

    def delete(self, torrent_id: str) -> None:
        self.deleted = True

    def close(self) -> None:
        self.closed = True

    def shutdown(self) -> None:
        self.shutdown_called = True


class _BatchClient(_FakeClient):
    def __init__(self, *, complete: bool = True) -> None:
        super().__init__(complete=complete)
        self.fetch_calls = 0
        self.add_calls = 0
        self.start_calls = 0
        self.stop_calls = 0
        self.delete_calls = 0

    def fetch_metadata(self, source: str) -> TorrentMetadata:
        self.fetch_calls += 1
        files = (
            TorrentMetadataFile(0, "PSP collection/unwanted.bin", 3),
            TorrentMetadataFile(1, QBITTORRENT_INTERNAL, len(PAYLOAD)),
            TorrentMetadataFile(2, QBITTORRENT_INTERNAL_2, len(PAYLOAD_2)),
        )
        return TorrentMetadata(
            torrent_id=INFOHASH,
            infohash_v1=INFOHASH,
            infohash_v2=None,
            name="PSP collection",
            files=files,
            total_size=sum(file.length for file in files),
        )

    def add(
        self,
        source: str,
        *,
        file_priorities,
        save_path: Path,
        tag: str,
        stopped: bool = True,
    ) -> AddResult:
        self.add_calls += 1
        return super().add(
            source,
            file_priorities=file_priorities,
            save_path=save_path,
            tag=tag,
            stopped=stopped,
        )

    def files(
        self, torrent_id: str, *, indexes=None
    ) -> tuple[dict[str, object], ...]:
        progress = 1.0 if self.started and self.complete else 0.0
        paths = (
            ("PSP collection/unwanted.bin", 3),
            (QBITTORRENT_INTERNAL, len(PAYLOAD)),
            (QBITTORRENT_INTERNAL_2, len(PAYLOAD_2)),
        )
        files: tuple[dict[str, object], ...] = tuple(
            {
                "index": index,
                "name": name,
                "size": size,
                "progress": progress if self.priorities[index] else 0.0,
                "priority": self.priorities[index],
            }
            for index, (name, size) in enumerate(paths)
        )
        if indexes is None:
            return files
        selected = set(indexes)
        return tuple(entry for entry in files if entry["index"] in selected)

    def start(self, torrent_id: str) -> None:
        self.start_calls += 1
        self.started = True
        self.stopped = False
        assert self.stage_root is not None
        for index, (name, payload) in enumerate(
            (
                ("PSP collection/unwanted.bin", b"bad"),
                (QBITTORRENT_INTERNAL, PAYLOAD),
                (QBITTORRENT_INTERNAL_2, PAYLOAD_2),
            )
        ):
            if not self.priorities[index]:
                continue
            output = self.stage_root / name
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(payload)

    def stop(self, torrent_id: str) -> None:
        self.stop_calls += 1
        super().stop(torrent_id)

    def delete(self, torrent_id: str) -> None:
        self.delete_calls += 1
        super().delete(torrent_id)


def _dispatcher(monkeypatch, coordinator: TorrentCoordinator) -> SourceDispatcher:
    import retrofetch.dispatcher as dispatcher_module

    monkeypatch.setitem(
        dispatcher_module._SOURCE_FACTORIES, "minerva_torrent", _TorrentSource
    )
    dispatcher = SourceDispatcher({}, ["minerva_torrent"])
    dispatcher.torrent_coordinator = coordinator
    return dispatcher


def test_transfer_many_unions_two_files_and_prepares_each(scratch_path) -> None:
    client = _BatchClient()
    state = State(console="psp")
    events: list[object] = []
    bus = EventBus()
    bus.subscribe(events.append)
    coordinator = TorrentCoordinator(
        Config(roms_root=scratch_path),
        threading.Event(),
        client=client,  # type: ignore[arg-type]
    )
    target = scratch_path / "psp"
    first = TorrentBatchItem(_candidate(), target, "Game", "item-1")
    second = TorrentBatchItem(_candidate_two(), target, "Game Two", "item-2")

    results = coordinator.transfer_many(
        [first, second], state=state, state_lock=None, event_bus=bus
    )

    first_prepared = results["item-1"]
    second_prepared = results["item-2"]
    assert isinstance(first_prepared, PreparedTorrent)
    assert isinstance(second_prepared, PreparedTorrent)
    assert first_prepared.staged_path.read_bytes() == PAYLOAD
    assert second_prepared.staged_path.read_bytes() == PAYLOAD_2
    assert client.fetch_calls == 1
    assert client.add_calls == client.start_calls == client.delete_calls == 1
    assert client.share_limits_set
    assert client.priorities == [0, 1, 1]
    assert [entry.selected_file_ids for entry in state.games] == [[1], [2]]
    assert {entry.infohash for entry in state.games} == {INFOHASH}
    tags = {entry.tag for entry in state.games}
    assert len(tags) == 1
    tag = next(iter(tags))
    assert isinstance(tag, str)
    assert tag.startswith(f"retrofetch-{INFOHASH[:12]}-")

    first_path = TorrentTransferSource(
        coordinator,
        source_name="minerva_torrent",
        game_title="Game",
        item_id="item-1",
        state=state,
        state_lock=None,
        prepared=first_prepared,
    ).download(_candidate(), target)
    second_path = TorrentTransferSource(
        coordinator,
        source_name="minerva_torrent",
        game_title="Game Two",
        item_id="item-2",
        state=state,
        state_lock=None,
        prepared=second_prepared,
    ).download(_candidate_two(), target)

    assert first_path.read_bytes() == PAYLOAD
    assert second_path.read_bytes() == PAYLOAD_2
    byte_item_ids = {
        event.item_id for event in events if isinstance(event, GameBytesEvent)
    }
    assert byte_item_ids == {"item-1", "item-2"}


def test_transfer_uses_qbittorrents_canonical_job_id(scratch_path) -> None:
    client = _FakeClient()
    client.job_id = "b" * 40
    candidate = _candidate()
    assert candidate.extra is not None
    candidate.extra["torrent_bytes"] = b"validated torrent metadata"
    state = State(console="psp")
    coordinator = TorrentCoordinator(
        Config(roms_root=scratch_path),
        threading.Event(),
        client=client,  # type: ignore[arg-type]
    )

    result = coordinator.transfer_many(
        [TorrentBatchItem(candidate, scratch_path / "psp", "Game", "item-1")],
        state=state,
        state_lock=None,
        event_bus=None,
    )["item-1"]

    assert isinstance(result, PreparedTorrent)
    assert state.games[0].infohash == INFOHASH


def test_url_metadata_fallback_adds_url_then_uses_canonical_job_id(
    scratch_path,
) -> None:
    client = _FakeClient()
    client.job_id = "b" * 40
    candidate = _candidate()
    coordinator = TorrentCoordinator(
        Config(roms_root=scratch_path),
        threading.Event(),
        client=client,  # type: ignore[arg-type]
    )

    result = coordinator.transfer_many(
        [TorrentBatchItem(candidate, scratch_path / "psp", "Game", "item-1")],
        state=State(console="psp"),
        state_lock=None,
        event_bus=None,
    )["item-1"]

    assert isinstance(result, PreparedTorrent)
    assert client.added_source == candidate.url


def test_invalid_carried_metadata_is_reported_per_item(scratch_path) -> None:
    candidate = _candidate()
    assert candidate.extra is not None
    candidate.extra["torrent_bytes"] = b""
    coordinator = TorrentCoordinator(
        Config(roms_root=scratch_path),
        threading.Event(),
        client=_FakeClient(),  # type: ignore[arg-type]
    )

    result = coordinator.transfer_many(
        [TorrentBatchItem(candidate, scratch_path / "psp", "Game", "item-1")],
        state=State(console="psp"),
        state_lock=None,
        event_bus=None,
    )["item-1"]

    assert isinstance(result, SourceUnavailable)
    assert "metadata bytes are invalid" in str(result)


def test_same_infohash_candidates_may_differ_outside_the_info_dictionary(
    scratch_path,
) -> None:
    client = _BatchClient()
    first = _candidate()
    second = _candidate_two()
    assert first.extra is not None and second.extra is not None
    first.extra["torrent_bytes"] = b"announce=A; shared info dictionary"
    second.extra["torrent_bytes"] = b"announce=B; shared info dictionary"
    coordinator = TorrentCoordinator(
        Config(roms_root=scratch_path),
        threading.Event(),
        client=client,  # type: ignore[arg-type]
    )

    results = coordinator.transfer_many(
        [
            TorrentBatchItem(first, scratch_path / "psp", "Game", "item-1"),
            TorrentBatchItem(second, scratch_path / "psp", "Game Two", "item-2"),
        ],
        state=State(console="psp"),
        state_lock=None,
        event_bus=None,
    )

    assert all(isinstance(result, PreparedTorrent) for result in results.values())


def test_single_transfer_reports_live_metrics_and_persists_progress(
    monkeypatch, scratch_path
) -> None:
    class _MetricsClient(_FakeClient):
        def info(self, torrent_id=None, *, tag=None):
            jobs = super().info(torrent_id, tag=tag)
            if not jobs:
                return jobs
            job = dict(jobs[0])
            job.update(dlspeed=5 * 1024**2, eta=95, num_seeds=11, num_leechs=17)
            return (job,)

    snapshots: list[list[tuple[str | None, int]]] = []

    def capture_state(current: State, _root: Path) -> None:
        snapshots.append(
            [(entry.phase, entry.completed_bytes) for entry in current.games]
        )

    monkeypatch.setattr(torrent_module, "save_state", capture_state)
    client = _MetricsClient()
    state = State(console="psp")
    events: list[object] = []
    bus = EventBus()
    bus.subscribe(events.append)
    coordinator = TorrentCoordinator(
        Config(roms_root=scratch_path),
        threading.Event(),
        client=client,  # type: ignore[arg-type]
    )
    item = TorrentBatchItem(_candidate(), scratch_path / "psp", "Game", "item-1")

    coordinator.transfer_many([item], state=state, state_lock=None, event_bus=bus)

    progress = next(event for event in events if isinstance(event, GameBytesEvent))
    assert (
        progress.speed_bps,
        progress.eta_seconds,
        progress.seeds,
        progress.peers,
    ) == (
        5 * 1024**2,
        95,
        11,
        28,
    )
    assert any(
        phase == "downloading" and completed == len(PAYLOAD)
        for snapshot in snapshots
        for phase, completed in snapshot
    )


def test_transfer_many_cancel_stops_one_group_and_marks_each(scratch_path) -> None:
    stop = threading.Event()
    stop.set()
    client = _BatchClient(complete=False)
    state = State(console="psp")
    coordinator = TorrentCoordinator(
        Config(roms_root=scratch_path),
        stop,
        client=client,  # type: ignore[arg-type]
    )
    target = scratch_path / "psp"

    results = coordinator.transfer_many(
        [
            TorrentBatchItem(_candidate(), target, "Game", "item-1"),
            TorrentBatchItem(_candidate_two(), target, "Game Two", "item-2"),
        ],
        state=state,
        state_lock=None,
        event_bus=None,
    )

    assert all(isinstance(result, DownloadCancelled) for result in results.values())
    assert client.add_calls == client.start_calls == 0
    assert client.stop_calls == 0
    assert client.delete_calls == 0
    assert state.games == []


def test_transfer_many_cancel_during_metadata_never_adds_or_starts(
    scratch_path,
) -> None:
    stop = threading.Event()

    class _CancelAfterMetadataClient(_BatchClient):
        def fetch_metadata(self, source: str) -> TorrentMetadata:
            metadata = super().fetch_metadata(source)
            stop.set()
            return metadata

    client = _CancelAfterMetadataClient(complete=False)
    coordinator = TorrentCoordinator(
        Config(roms_root=scratch_path),
        stop,
        client=client,  # type: ignore[arg-type]
    )

    results = coordinator.transfer_many(
        [TorrentBatchItem(_candidate(), scratch_path / "psp", "Game", "item-1")],
        state=State(console="psp"),
        state_lock=None,
        event_bus=None,
    )

    assert isinstance(results["item-1"], DownloadCancelled)
    assert client.add_calls == client.start_calls == 0


def test_transfer_many_verifies_share_limits_before_start(scratch_path) -> None:
    class _UnsafeShareLimitsClient(_BatchClient):
        def set_share_limits(self, torrent_id: str) -> None:
            pass

    client = _UnsafeShareLimitsClient()
    state = State(console="psp")
    coordinator = TorrentCoordinator(
        Config(roms_root=scratch_path),
        threading.Event(),
        client=client,  # type: ignore[arg-type]
    )
    target = scratch_path / "psp"

    results = coordinator.transfer_many(
        [
            TorrentBatchItem(_candidate(), target, "Game", "item-1"),
            TorrentBatchItem(_candidate_two(), target, "Game Two", "item-2"),
        ],
        state=state,
        state_lock=None,
        event_bus=None,
    )

    assert all(
        isinstance(result, SourceUnavailable) and "zero share limits" in str(result)
        for result in results.values()
    )
    assert client.start_calls == 0


def test_transfer_resume_counts_existing_partial_bytes_for_free_space(
    monkeypatch: pytest.MonkeyPatch, scratch_path: Path
) -> None:
    target = scratch_path / "psp"
    stage = target / ".retrofetch-staging" / INFOHASH
    partial = stage / "PSP collection" / INTERNAL
    partial.parent.mkdir(parents=True)
    partial.write_bytes(PAYLOAD[:10])
    remaining = len(PAYLOAD) - 10
    monkeypatch.setattr(
        "retrofetch.torrent.shutil.disk_usage",
        lambda _path: SimpleNamespace(free=64 * 1024 * 1024 + remaining),
    )
    client = _BatchClient()
    coordinator = TorrentCoordinator(
        Config(roms_root=scratch_path),
        threading.Event(),
        client=client,  # type: ignore[arg-type]
    )

    result = coordinator.transfer_many(
        [TorrentBatchItem(_candidate(), target, "Game", "item-1")],
        state=State(console="psp"),
        state_lock=None,
        event_bus=None,
    )

    assert isinstance(result["item-1"], PreparedTorrent)
    assert client.start_calls == 1


def test_dispatcher_downloads_only_exact_torrent_file(
    monkeypatch, scratch_path
) -> None:
    client = _FakeClient()
    state = State(console="psp")
    events: list[object] = []
    bus = EventBus()
    bus.subscribe(events.append)
    coordinator = TorrentCoordinator(
        Config(roms_root=scratch_path),
        threading.Event(),
        client=client,  # type: ignore[arg-type]
    )

    result = _dispatcher(monkeypatch, coordinator).dispatch_download(
        game_title="Game",
        game=None,
        target_dir=scratch_path / "psp",
        region_priority=["USA"],
        state=state,
        console="psp",
        event_bus=bus,
        verification_available=False,
    )

    assert result.status == "unverified"
    assert (scratch_path / "psp" / "Game (USA).zip").read_bytes() == PAYLOAD
    assert client.priorities == [0, 1]
    assert client.stopped and client.deleted
    assert state.games[0].infohash == INFOHASH
    assert state.games[0].outcome == "acquired"
    assert state.games[0].verification == "unverified"
    assert any(isinstance(event, GameStageEvent) for event in events)


def test_cancel_stops_and_keeps_owned_job_for_resume(monkeypatch, scratch_path) -> None:
    stop = threading.Event()
    stop.set()
    client = _FakeClient(complete=False)
    state = State(console="psp")
    events: list[object] = []
    bus = EventBus()
    bus.subscribe(events.append)
    coordinator = TorrentCoordinator(
        Config(roms_root=scratch_path),
        stop,
        client=client,  # type: ignore[arg-type]
    )

    result = _dispatcher(monkeypatch, coordinator).dispatch_download(
        game_title="Game",
        game=None,
        target_dir=scratch_path / "psp",
        region_priority=["USA"],
        state=state,
        console="psp",
        event_bus=bus,
        verification_available=False,
    )

    assert result.status == "cancelled"
    assert not client.stopped and not client.deleted
    assert state.games[0].outcome == "cancelled"
    assert any(isinstance(event, GameCancelledEvent) for event in events)


def test_existing_unowned_same_hash_is_never_hijacked(
    monkeypatch, scratch_path
) -> None:
    client = _FakeClient(owned=False)
    coordinator = TorrentCoordinator(
        Config(roms_root=scratch_path),
        threading.Event(),
        client=client,  # type: ignore[arg-type]
    )

    result = _dispatcher(monkeypatch, coordinator).dispatch_download(
        game_title="Game",
        game=None,
        target_dir=scratch_path / "psp",
        region_priority=["USA"],
        state=State(console="psp"),
        console="psp",
        verification_available=False,
    )

    assert result.status == "failed"
    assert result.reason and "not owned by Retrofetch" in result.reason
    assert not client.started


def test_selected_casefold_collision_fails_before_add(
    monkeypatch, scratch_path
) -> None:
    client = _FakeClient(selected_collision=True)
    coordinator = TorrentCoordinator(
        Config(roms_root=scratch_path),
        threading.Event(),
        client=client,  # type: ignore[arg-type]
    )

    result = _dispatcher(monkeypatch, coordinator).dispatch_download(
        game_title="Game",
        game=None,
        target_dir=scratch_path / "psp",
        region_priority=["USA"],
        state=State(console="psp"),
        console="psp",
        verification_available=False,
    )

    assert result.status == "failed"
    assert not client.added


def test_linux_appimage_setup_verifies_and_copies_download(
    monkeypatch, scratch_path
) -> None:
    content = b"official qBittorrent AppImage"
    name = "qbittorrent-5.2.3_x86_64.AppImage"
    downloads = scratch_path / "Downloads"
    downloads.mkdir()
    (downloads / name).write_bytes(content)
    root = scratch_path / "app" / "qbittorrent"
    paths = ManagedPaths(
        root,
        root / "profile",
        root / "profile" / "qBittorrent.conf",
        root / "managed.lock",
    )
    monkeypatch.setattr(torrent_module.sys, "platform", "linux")
    monkeypatch.setattr(
        torrent_module,
        "QBITTORRENT_LINUX_APPIMAGES",
        {name: hashlib.sha256(content).hexdigest()},
    )
    monkeypatch.setattr(torrent_module, "managed_paths", lambda: paths)
    monkeypatch.setattr(
        torrent_module,
        "discover_qbittorrent",
        lambda explicit=None: Path(explicit).resolve() if explicit else None,
    )

    executable = torrent_module.install_qbittorrent_appimage(downloads)

    assert executable == (root / "bin" / name).resolve()
    assert executable.read_bytes() == content


def test_setup_decline_is_cached_and_gate_never_accepts_after_stop(
    monkeypatch, scratch_path
) -> None:
    import retrofetch.torrent as torrent_module

    paths = ManagedPaths(
        scratch_path / "runtime",
        scratch_path / "runtime" / "profile",
        scratch_path / "runtime" / "profile" / "qBittorrent.ini",
        scratch_path / "runtime" / "lock",
    )
    monkeypatch.setattr(torrent_module, "managed_paths", lambda: paths)
    monkeypatch.setattr(torrent_module, "discover_qbittorrent", lambda *_: None)
    calls = 0

    def decline() -> bool:
        nonlocal calls
        calls += 1
        return False

    coordinator = TorrentCoordinator(
        Config(roms_root=scratch_path), threading.Event(), setup_callback=decline
    )
    for _ in range(2):
        with pytest.raises(SourceUnavailable, match="declined"):
            coordinator._ensure_client()
    assert calls == 1

    gate = TorrentSetupGate()
    stop = threading.Event()
    stop.set()
    gate.resolve(True)
    assert gate.wait(stop) is False


def test_managed_runtime_record_reattaches_after_parent_crash(
    monkeypatch, scratch_path
) -> None:
    import retrofetch.torrent as torrent_module

    root = scratch_path / "runtime"
    paths = ManagedPaths(
        root,
        root / "profile",
        root / "profile" / "qBittorrent.ini",
        root / "lock",
    )
    paths.root.mkdir(parents=True)
    (paths.root / torrent_module._SETUP_MARKER).write_text("accepted")
    executable = scratch_path / "qbittorrent.exe"
    executable.touch()
    record = paths.root / torrent_module._RUNTIME_RECORD
    torrent_module._write_runtime_record(
        record,
        api_key="qbt_" + "A" * 28,
        port=9191,
        executable=executable,
        pid=4242,
        launch_time=1_725_000_000,
    )
    paths.config.parent.mkdir(parents=True)
    paths.config.write_text(
        f"[Preferences]\nWebUI\\APIKey={'qbt_' + 'A' * 28}\n",
        encoding="utf-8",
    )
    client = _FakeClient()
    monkeypatch.setattr(torrent_module, "managed_paths", lambda: paths)
    monkeypatch.setattr(
        torrent_module, "QbittorrentClient", lambda *_args, **_kwargs: client
    )
    monkeypatch.setattr(
        torrent_module, "discover_qbittorrent", lambda explicit=None: executable
    )
    monkeypatch.setattr(
        torrent_module,
        "_windows_process_identity",
        lambda pid: (executable.resolve(), 1_725_000_000),
    )

    coordinator = TorrentCoordinator(Config(roms_root=scratch_path), threading.Event())
    assert coordinator._ensure_client() is client
    coordinator.close()

    assert client.shutdown_called and client.closed
    assert not record.exists()


def test_finalizing_state_adopts_already_promoted_exact_file(scratch_path) -> None:
    target = scratch_path / "psp"
    target.mkdir()
    final = target / "Game (USA).zip"
    final.write_bytes(PAYLOAD)
    state = State(
        console="psp",
        games=[
            GameEntry(
                title="Game",
                item_id="item",
                status="pending",
                infohash=INFOHASH,
                selected_paths=[INTERNAL],
                final_path=str(final),
                phase="finalizing",
            )
        ],
    )
    client = _FakeClient()
    coordinator = TorrentCoordinator(
        Config(roms_root=scratch_path),
        threading.Event(),
        client=client,  # type: ignore[arg-type]
    )
    source = TorrentTransferSource(
        coordinator,
        source_name="minerva_torrent",
        game_title="Game",
        item_id="item",
        state=state,
        state_lock=None,
    )

    assert source.download(_candidate(), target) == final
    assert not client.added
