from __future__ import annotations

import statistics
import threading

import retrofetch.torrent as torrent_module
from retrofetch.config import Config
from retrofetch.state import State
from retrofetch.torrent import PreparedTorrent, TorrentBatchItem, TorrentCoordinator
from tests.test_minerva_torrent import _FixtureSource, _entry, _torrent
from tests.test_torrent import (
    INFOHASH,
    INTERNAL,
    PAYLOAD,
    _BatchClient,
    _FakeClient,
    _candidate,
    _candidate_two,
)


TORRENT_BYTES = b"candidate-carried-torrent-metadata"


class _TimedClient(_FakeClient):
    def __init__(self) -> None:
        super().__init__()
        self.external_metadata_fetches = 0
        self.parse_calls = 0
        self.parsed_content: bytes | None = None
        self.added_source: str | None = None
        self.priority_calls: list[tuple[tuple[int, ...], int]] = []
        self.virtual_metadata_ms = 0

    def fetch_metadata(self, source: str):
        self.external_metadata_fetches += 1
        self.virtual_metadata_ms += 8_000
        return super().fetch_metadata(source)

    def parse_metadata(self, content: bytes, *, filename: str = "metadata.torrent"):
        self.parse_calls += 1
        self.parsed_content = content
        self.virtual_metadata_ms += 40
        return super().fetch_metadata(filename)

    def add(self, source: str, **kwargs):
        carried = kwargs.pop("torrent_bytes", source)
        self.added_source = source
        if isinstance(carried, bytes):
            self.virtual_metadata_ms += 40
        elif not self.external_metadata_fetches and not self.parse_calls:
            self.virtual_metadata_ms += 8_000
        result = super().add(source, **kwargs)
        self.stopped = bool(kwargs.get("stopped", True))
        return result

    def set_file_priority(self, torrent_id: str, indexes, priority: int) -> None:
        values = (indexes,) if isinstance(indexes, int) else tuple(indexes)
        self.priority_calls.append((values, priority))
        super().set_file_priority(torrent_id, values, priority)


def _carried_candidate():
    candidate = _candidate()
    assert candidate.extra is not None
    candidate.extra["torrent_bytes"] = TORRENT_BYTES
    return candidate


def _transfer(tmp_path, client: _TimedClient):
    coordinator = TorrentCoordinator(
        Config(roms_root=tmp_path),
        threading.Event(),
        client=client,  # type: ignore[arg-type]
    )
    return coordinator.transfer_many(
        [
            TorrentBatchItem(
                _carried_candidate(), tmp_path / "psp", "Game", "item-1"
            )
        ],
        state=State(console="psp"),
        state_lock=None,
        event_bus=None,
    )["item-1"]


def test_minerva_candidate_carries_the_exact_fetched_torrent_bytes() -> None:
    path = f"{INTERNAL}"
    torrent_bytes, _infohash = _torrent(
        {b"length": len(PAYLOAD), b"path": [part.encode() for part in path.split("/")]}
    )
    candidate = _FixtureSource(_entry(path), torrent_bytes).find_url_for_game(
        "Example Game", ["USA"]
    )

    assert candidate is not None
    assert candidate.extra is not None
    assert candidate.extra["torrent_bytes"] == torrent_bytes


def test_carried_bytes_remove_qbittorrent_refetch_and_cut_mocked_p95(
    tmp_path,
) -> None:
    client = _TimedClient()

    assert isinstance(_transfer(tmp_path, client), PreparedTorrent)
    assert client.external_metadata_fetches == 0
    assert client.parse_calls == 1
    assert client.parsed_content == TORRENT_BYTES
    assert client.added_source == INFOHASH

    # Live PSP resolution measured ~14 s plus ~8 s for qB's redundant fetch.
    candidate_ms = [13_500 + 50 * sample for sample in range(20)]
    qbit_refetch_ms = [7_000 + 100 * sample for sample in range(20)]
    baseline = [a + b for a, b in zip(candidate_ms, qbit_refetch_ms, strict=True)]
    optimized = [value + client.virtual_metadata_ms for value in candidate_ms]

    def p95(values: list[int]) -> float:
        return statistics.quantiles(values, n=100, method="inclusive")[94]

    assert p95(optimized) <= p95(baseline) * 0.75


def test_new_stopped_job_keeps_add_time_priorities_without_reset(tmp_path) -> None:
    client = _TimedClient()

    assert isinstance(_transfer(tmp_path, client), PreparedTorrent)
    assert client.priorities == [0, 1]
    assert client.priority_calls == []


def test_batched_progress_persists_once_per_poll(monkeypatch, tmp_path) -> None:
    class _PollingBatchClient(_BatchClient):
        progress_polls = 0

        def parse_metadata(self, content: bytes, *, filename: str = "metadata.torrent"):
            return super().fetch_metadata(filename)

        def files(self, torrent_id: str, *, indexes=None):
            if self.started:
                self.progress_polls += 1
            return super().files(torrent_id, indexes=indexes)

    progress_saves = 0

    def capture_progress(state: State, _root) -> None:
        nonlocal progress_saves
        if (
            len(state.games) == 2
            and all(entry.phase == "downloading" for entry in state.games)
            and any(entry.completed_bytes for entry in state.games)
        ):
            progress_saves += 1

    monkeypatch.setattr(torrent_module, "save_state", capture_progress)
    client = _PollingBatchClient()
    first = _candidate()
    second = _candidate_two()
    assert first.extra is not None and second.extra is not None
    first.extra["torrent_bytes"] = TORRENT_BYTES
    second.extra["torrent_bytes"] = TORRENT_BYTES
    coordinator = TorrentCoordinator(
        Config(roms_root=tmp_path), threading.Event(), client=client  # type: ignore[arg-type]
    )

    results = coordinator.transfer_many(
        [
            TorrentBatchItem(first, tmp_path / "psp", "Game", "item-1"),
            TorrentBatchItem(second, tmp_path / "psp", "Game Two", "item-2"),
        ],
        state=State(console="psp"),
        state_lock=None,
        event_bus=None,
    )

    assert all(isinstance(result, PreparedTorrent) for result in results.values())
    assert progress_saves == client.progress_polls == 1
