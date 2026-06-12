from __future__ import annotations

import hashlib
import http.server
import socketserver
import threading
import zipfile
from pathlib import Path
from typing import Any, cast

import pytest

from retrofetch.dat import GameEntry as DatGameEntry, Rom
from retrofetch.dispatcher import SourceDispatcher
from retrofetch.downloader import download_game, stream_http_download
from retrofetch.events import EventBus, GameSkippedEvent
from retrofetch.sources import DownloadCandidate, SourceUnavailable
from retrofetch.state import GameEntry, State


PAYLOAD = (b"0123456789abcdef" * 65536)[: 1024 * 1024]


class _ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


class _PayloadServer:
    def __init__(
        self,
        *,
        payload: bytes = PAYLOAD,
        support_range: bool = True,
        include_length: bool = True,
        disconnect_after: int | None = None,
    ) -> None:
        self.state: dict[str, Any] = {
            "payload": payload,
            "support_range": support_range,
            "include_length": include_length,
            "disconnect_after": disconnect_after,
            "requests": [],
        }

        state = self.state

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:
                return

            def do_HEAD(self) -> None:
                state["requests"].append(("HEAD", self.headers.get("Range")))
                self.send_response(200)
                if state["support_range"]:
                    self.send_header("Accept-Ranges", "bytes")
                if state["include_length"]:
                    self.send_header("Content-Length", str(len(state["payload"])))
                self.end_headers()

            def do_GET(self) -> None:
                range_header = self.headers.get("Range")
                state["requests"].append(("GET", range_header))
                payload: bytes = state["payload"]
                disconnect_after = state["disconnect_after"]
                if disconnect_after is not None:
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload[:disconnect_after])
                    self.wfile.flush()
                    self.connection.close()
                    return
                if range_header and state["support_range"]:
                    start = int(range_header.split("=", 1)[1].split("-", 1)[0])
                    body = payload[start:]
                    self.send_response(206)
                    self.send_header("Accept-Ranges", "bytes")
                    self.send_header("Content-Range", f"bytes {start}-{len(payload) - 1}/{len(payload)}")
                    if state["include_length"]:
                        self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                self.send_response(200)
                if state["support_range"]:
                    self.send_header("Accept-Ranges", "bytes")
                if state["include_length"]:
                    self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        self.server = _ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        host, port = cast(tuple[str, int], self.server.server_address)
        return f"http://{host}:{port}/payload.bin"

    @property
    def requests(self) -> list[tuple[str, str | None]]:
        return list(self.state["requests"])

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


@pytest.fixture
def payload_server():
    servers: list[_PayloadServer] = []

    def make(**kwargs: Any) -> _PayloadServer:
        server = _PayloadServer(**kwargs)
        servers.append(server)
        return server

    yield make

    for server in servers:
        server.close()


def test_stream_http_download_fresh(payload_server, scratch_path) -> None:
    server = payload_server()
    final = scratch_path / "game.bin"

    result = stream_http_download(server.url, final, source_name="test")

    assert result.path == final
    assert final.read_bytes() == PAYLOAD
    assert not final.with_suffix(".bin.part").exists()


def test_stream_http_download_resumes_from_part(payload_server, scratch_path) -> None:
    server = payload_server(support_range=True)
    final = scratch_path / "game.bin"
    part = final.with_suffix(".bin.part")
    part.write_bytes(PAYLOAD[:100])

    stream_http_download(server.url, final, source_name="test")

    assert final.read_bytes() == PAYLOAD
    assert ("GET", "bytes=100-") in server.requests


def test_stream_http_download_restarts_when_range_unsupported(payload_server, scratch_path) -> None:
    server = payload_server(support_range=False)
    final = scratch_path / "game.bin"
    final.with_suffix(".bin.part").write_bytes(b"bad-prefix")

    stream_http_download(server.url, final, source_name="test")

    assert final.read_bytes() == PAYLOAD
    assert all(range_header is None for method, range_header in server.requests if method == "GET")


def test_stream_http_download_discards_part_larger_than_remote(payload_server, scratch_path) -> None:
    server = payload_server(payload=b"small", support_range=True)
    final = scratch_path / "game.bin"
    final.with_suffix(".bin.part").write_bytes(b"small plus stale bytes")

    stream_http_download(server.url, final, source_name="test")

    assert final.read_bytes() == b"small"
    assert all(range_header is None for method, range_header in server.requests if method == "GET")


def test_stream_http_download_allows_missing_content_length(payload_server, scratch_path) -> None:
    server = payload_server(include_length=False)
    final = scratch_path / "game.bin"

    stream_http_download(server.url, final, source_name="test")

    assert final.read_bytes() == PAYLOAD


def test_stream_http_download_interruption_leaves_part(payload_server, scratch_path) -> None:
    server = payload_server(disconnect_after=300_000)
    final = scratch_path / "game.bin"

    with pytest.raises(SourceUnavailable):
        stream_http_download(server.url, final, source_name="test")

    assert not final.exists()
    assert final.with_suffix(".bin.part").exists()


def test_dispatcher_skips_already_acquired_without_source_lookup(scratch_path) -> None:
    target_dir = scratch_path / "roms"
    target_dir.mkdir()
    (target_dir / "Game.zip").write_bytes(b"existing")
    state = State(
        console="nes",
        games=[GameEntry(title="Game", status="acquired", filename="Game.zip")],
    )
    events = []
    bus = EventBus()
    bus.subscribe(events.append)
    dispatcher = SourceDispatcher({}, ["unknown"])

    result = dispatcher.dispatch_download(
        game_title="Game",
        game=None,
        target_dir=target_dir,
        region_priority=["USA"],
        state=state,
        console="nes",
        event_bus=bus,
    )

    assert result.status == "skipped"
    assert any(isinstance(event, GameSkippedEvent) for event in events)


class _ZipSource:
    name = "zip_source"

    def __init__(self, payload: bytes = b"rom bytes") -> None:
        self.payload = payload

    def find_url_for_game(self, title: str, region_priority: list[str] | None = None):
        return None

    def download(self, candidate: DownloadCandidate, dest_dir: Path, *, event_bus=None) -> Path:
        final = Path(dest_dir) / candidate.filename
        with zipfile.ZipFile(final, "w") as zf:
            zf.writestr("Game.sfc", self.payload)
        return final


def test_download_game_keeps_archive_by_default(scratch_path) -> None:
    state = State(console="snes")
    candidate = DownloadCandidate(
        url="https://example/game.zip",
        filename="Game (USA).zip",
        source="zip_source",
    )

    result = download_game(
        _ZipSource(),
        candidate,
        scratch_path,
        None,
        "Game",
        state,
        console="snes",
    )

    assert result.status == "acquired"
    assert (scratch_path / "Game (USA).zip").exists()
    assert not (scratch_path / "Game.sfc").exists()


def test_download_game_extracts_when_enabled(scratch_path) -> None:
    state = State(console="snes")
    candidate = DownloadCandidate(
        url="https://example/game.zip",
        filename="Game (USA).zip",
        source="zip_source",
    )

    result = download_game(
        _ZipSource(),
        candidate,
        scratch_path,
        None,
        "Game",
        state,
        console="snes",
        extract_archives=True,
    )

    assert result.status == "acquired"
    assert not (scratch_path / "Game (USA).zip").exists()
    assert (scratch_path / "Game.sfc").exists()


def test_download_game_verifies_zip_member_without_extraction(scratch_path) -> None:
    payload = b"verified rom"
    sha1 = hashlib.sha1(payload).hexdigest()
    state = State(console="snes")
    candidate = DownloadCandidate(
        url="https://example/game.zip",
        filename="Game (USA).zip",
        source="zip_source",
    )
    game = DatGameEntry(
        name="Game",
        description="Game",
        category=None,
        roms=[Rom(name="Game.sfc", size=len(payload), sha1=sha1)],
    )

    result = download_game(
        _ZipSource(payload),
        candidate,
        scratch_path,
        game,
        "Game",
        state,
        console="snes",
    )

    assert result.status == "acquired"
    assert (scratch_path / "Game (USA).zip").exists()
