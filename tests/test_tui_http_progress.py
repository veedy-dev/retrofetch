from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from queue import Queue
from threading import Barrier

import httpx
import pytest

from retrofetch.downloader import download_game, stream_http_download
from retrofetch.events import EventBus, GameBytesEvent, GameStartEvent, RateLimitEvent
from retrofetch.sources import DownloadCandidate
from retrofetch.state import State
from retrofetch.tui.downloads import DownloadSession
from retrofetch.tui.messages import EventBusBridge, GameBytes


@pytest.mark.parametrize(
    "titles", [("Display Title",), ("First Title", "Second Title")]
)
def test_http_progress_tracks_only_canonical_items(monkeypatch, scratch_path, titles):
    payload = b"test payload" * 16384
    barrier = Barrier(len(titles) + 1)
    release = Barrier(len(titles) + 1)
    bus = EventBus()
    messages = Queue()
    bridge = EventBusBridge(messages.put, bus)
    session = DownloadSession({"shortname": "test"}, [*titles, "Pending Sibling"])
    bridge.start()

    class Stream(httpx.SyncByteStream):
        def __iter__(self):
            yield payload[:65536]
            barrier.wait(timeout=10)
            release.wait(timeout=10)
            yield payload[65536:]

    client = httpx.Client
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200, headers={"Content-Length": str(len(payload))}, stream=Stream()
        )
    )
    monkeypatch.setattr(
        "retrofetch.downloader.httpx.Client",
        lambda **kwargs: client(transport=transport, **kwargs),
    )

    class Source:
        name = "mock-http"

        def __init__(self):
            self.bus: EventBus | None = None

        def find_url_for_game(self, title, region_priority=None):
            return None

        def download(
            self, candidate, dest_dir: Path, *, event_bus: EventBus | None = None
        ):
            assert event_bus is not None
            self.bus = event_bus
            event_bus.publish(RateLimitEvent(self.name, 2))
            return stream_http_download(
                candidate.url, dest_dir / candidate.filename, event_bus=event_bus
            ).path

    sources = [Source() for _ in titles]
    paths = [
        scratch_path / str(index) / "shared-archive.zip" for index in range(len(titles))
    ]
    progress = []

    def drain():
        while not messages.empty():
            message = messages.get_nowait()
            session.apply(message)
            if isinstance(message, GameBytes):
                progress.append(
                    (
                        message.game,
                        session.active[message.item_id or message.game].downloaded,
                    )
                )

    try:
        with ThreadPoolExecutor(max_workers=len(titles)) as executor:
            futures = []
            for index, title in enumerate(titles):
                item_id = f"canonical-{index}"
                bus.publish(GameStartEvent(title, "mock-http", "test", item_id=item_id))
                candidate = DownloadCandidate(
                    f"https://mock-{index}.invalid/shared-archive.zip",
                    paths[index].name,
                    "mock-http",
                    expected_size=len(payload),
                )
                futures.append(
                    executor.submit(
                        download_game,
                        sources[index],
                        candidate,
                        paths[index].parent,
                        None,
                        title,
                        State(console="test"),
                        console="test",
                        event_bus=bus,
                        item_id=item_id,
                        verification_available=False,
                    )
                )
            try:
                barrier.wait(timeout=10)
                drain()
                assert set(session.active) == {
                    f"canonical-{i}" for i in range(len(titles))
                }
                assert {item.title for item in session.active.values()} == set(titles)
                assert all(item.downloaded == 65536 for item in session.active.values())
                assert (
                    session.title_status.get("Pending Sibling", "Pending") == "Pending"
                )
                assert all(
                    not path.exists() and path.with_suffix(".zip.part").exists()
                    for path in paths
                )
                assert len(session.notices) == len(titles)
            finally:
                release.wait(timeout=10)
            assert all(
                future.result(timeout=10).status == "unverified" for future in futures
            )
        drain()
        assert session.active == {}
        assert session.unverified == len(titles)
        assert {record.title for record in session.recent} == set(titles)
        assert set(session.title_status) == set(titles)
        for title, path in zip(titles, paths):
            assert [downloaded for game, downloaded in progress if game == title] == [
                65536,
                131072,
                len(payload),
            ]
            assert path.read_bytes() == payload
            assert not path.with_suffix(".zip.part").exists()
        for source in sources:
            assert source.bus is not None
            source.bus.publish(GameBytesEvent("late archive", 1, 2))
            source.bus.publish(RateLimitEvent("late provider", 99))
        assert messages.empty()
    finally:
        bridge.stop()


def test_retry_progress_and_cancellation_release_provider_bus(scratch_path):
    from retrofetch.sources import DownloadCancelled

    bus = EventBus()
    messages = Queue()
    bridge = EventBusBridge(messages.put, bus)
    session = DownloadSession(
        {"shortname": "test"}, ["Display Title", "Pending Sibling"]
    )

    class Source:
        name = "retry-source"
        calls = 0
        retained_bus: EventBus | None = None

        def find_url_for_game(self, title, region_priority=None):
            return None

        def download(self, candidate, dest_dir, *, event_bus: EventBus | None = None):
            assert event_bus is not None
            self.retained_bus = event_bus
            self.calls += 1
            if self.calls == 1:
                raise TypeError("provider error, not a legacy signature")
            event_bus.publish(
                GameBytesEvent(
                    "archive.zip",
                    64,
                    128,
                    speed_bps=32,
                    eta_seconds=2,
                    seeds=3,
                    peers=4,
                )
            )
            raise DownloadCancelled()

    source = Source()
    bridge.start()
    try:
        bus.publish(
            GameStartEvent("Display Title", source.name, "test", item_id="item")
        )
        result = download_game(
            source,
            DownloadCandidate(
                "https://mock.invalid/archive.zip", "archive.zip", source.name
            ),
            scratch_path,
            None,
            "Display Title",
            State(console="test"),
            console="test",
            event_bus=bus,
            item_id="item",
        )
        assert result.status == "cancelled"
        assert source.calls == 2
        while not messages.empty():
            message = messages.get_nowait()
            session.apply(message)
            if isinstance(message, GameBytes):
                assert set(session.active) == {"item"}
                item = session.active["item"]
                assert (
                    item.downloaded,
                    item.total,
                    item.speed_bps,
                    item.eta_seconds,
                    item.seeds,
                    item.peers,
                ) == (64, 128, 32, 2, 3, 4)
        assert not session.active
        assert session.cancelled == 1
        assert set(session.title_status) == {"Display Title"}
        assert source.retained_bus is not None
        source.retained_bus.publish(RateLimitEvent("late source", 2))
        assert messages.empty()
    finally:
        bridge.stop()
