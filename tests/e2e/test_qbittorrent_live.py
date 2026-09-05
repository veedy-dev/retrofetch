from __future__ import annotations

import hashlib
import http.server
import logging
import os
import socket
import tempfile
import threading
import time
from pathlib import Path

import pytest

from retrofetch.config import Config
from retrofetch.downloader import download_game
from retrofetch.qbittorrent import (
    QbittorrentClient,
    discover_qbittorrent,
    generate_api_key,
    managed_paths,
    start_managed,
)
from retrofetch.sources import DownloadCancelled, DownloadCandidate
from retrofetch.state import State
from retrofetch.torrent import (
    PreparedTorrent,
    TorrentBatchItem,
    TorrentCoordinator,
    TorrentTransferSource,
)

logger = logging.getLogger(__name__)

pytestmark = pytest.mark.skipif(
    os.name != "nt" or os.environ.get("RETROFETCH_RUN_QB_E2E") != "1",
    reason="set RETROFETCH_RUN_QB_E2E=1 on Windows with qBittorrent 5.2.3",
)


def _bencode(value: object) -> bytes:
    if isinstance(value, int):
        return b"i" + str(value).encode() + b"e"
    if isinstance(value, bytes):
        return str(len(value)).encode() + b":" + value
    if isinstance(value, list):
        return b"l" + b"".join(_bencode(item) for item in value) + b"e"
    if isinstance(value, dict):
        return (
            b"d"
            + b"".join(
                _bencode(key) + _bencode(value[key]) for key in sorted(value)
            )
            + b"e"
        )
    raise TypeError(type(value))


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for(predicate, timeout: float = 20) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError("timed out waiting for live qBittorrent")
        time.sleep(0.05)


def _metadata(client: QbittorrentClient, url: str) -> None:
    deadline = time.monotonic() + 15
    while client.fetch_metadata(url).pending:
        if time.monotonic() >= deadline:
            raise AssertionError("live qBittorrent metadata timed out")
        time.sleep(0.05)


def test_real_exact_file_cancel_resume_and_finalize() -> None:
    executable = discover_qbittorrent()
    if executable is None:
        pytest.skip("pinned qBittorrent is not installed")

    wanted = (b"Retrofetch legal transfer fixture.\n" * 131_072)[: 3 * 1024**2]
    unwanted = b"This file must never be downloaded.\n" * 1024
    piece_length = 16_384
    payload = wanted + unwanted
    pieces = b"".join(
        hashlib.sha1(payload[offset : offset + piece_length]).digest()
        for offset in range(0, len(payload), piece_length)
    )
    info = {
        b"files": [
            {b"length": len(wanted), b"path": [b"wanted.bin"]},
            {b"length": len(unwanted), b"path": [b"unwanted.bin"]},
        ],
        b"name": b"fixture",
        b"piece length": piece_length,
        b"pieces": pieces,
    }
    torrent_bytes = _bencode({b"info": info})
    infohash = hashlib.sha1(_bencode(info)).hexdigest()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "application/x-bittorrent")
            self.send_header("Content-Length", str(len(torrent_bytes)))
            self.end_headers()
            self.wfile.write(torrent_bytes)

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    url = f"http://127.0.0.1:{server.server_port}/Legal%20Fixture.torrent"

    with tempfile.TemporaryDirectory(
        prefix="retrofetch-qb-e2e-", ignore_cleanup_errors=True
    ) as temporary:
        root = Path(temporary)
        seed = start_managed(
            executable,
            managed_paths(root / "seed-profile"),
            api_key=generate_api_key(),
            port=_free_port(),
            legal_notice_accepted=True,
        )
        leech = start_managed(
            executable,
            managed_paths(root / "leech-profile"),
            api_key=generate_api_key(),
            port=_free_port(),
            legal_notice_accepted=True,
        )
        try:
            _metadata(seed.client, url)
            _metadata(leech.client, url)
            seed_root = (root / "seed-data").resolve()
            (seed_root / "fixture").mkdir(parents=True)
            (seed_root / "fixture" / "wanted.bin").write_bytes(wanted)
            (seed_root / "fixture" / "unwanted.bin").write_bytes(unwanted)
            seed.client.add(
                url,
                file_priorities=[1, 1],
                save_path=seed_root,
                tag="retrofetch-legal-seed",
                stopped=True,
            )
            _wait_for(lambda: bool(seed.client.info(infohash)))
            seed.client._request(
                "POST",
                "torrents/setShareLimits",
                data={
                    "hashes": infohash,
                    "ratioLimit": "-1",
                    "seedingTimeLimit": "-1",
                    "inactiveSeedingTimeLimit": "-1",
                    "shareLimitAction": "Default",
                },
            )
            seed.client._request(
                "POST",
                "torrents/setUploadLimit",
                data={"hashes": infohash, "limit": "65536"},
            )
            seed.client.start(infohash)
            _wait_for(
                lambda: str(seed.client.info(infohash)[0].get("state", ""))
                .casefold()
                .endswith("up")
            )
            peer = f"127.0.0.1:{seed.client.preferences()['listen_port']}"

            stop = threading.Event()
            state = State(console="fixture")
            target = root / "roms" / "fixture"
            candidate = DownloadCandidate(
                url=url,
                filename="wanted.bin",
                source="legal_fixture",
                expected_size=len(wanted),
                extra={
                    "transport": "torrent",
                    "torrent_url": url,
                    "torrent_infohash": infohash,
                    "torrent_internal_path": "wanted.bin",
                    "torrent_file_index": 0,
                    "torrent_name": "fixture",
                    "torrent_bytes": torrent_bytes,
                },
            )
            coordinator = TorrentCoordinator(
                Config(roms_root=root / "roms"),
                stop,
                client=leech.client,
            )

            first: dict[str, object] = {}

            def transfer_once(destination: dict[str, object]) -> None:
                destination.update(
                    coordinator.transfer_many(
                        [TorrentBatchItem(candidate, target, "Legal fixture", "item")],
                        state=state,
                        state_lock=None,
                        event_bus=None,
                    )
                )

            worker = threading.Thread(target=transfer_once, args=(first,))
            worker.start()
            _wait_for(lambda: bool(leech.client.info(infohash)))
            leech.client._request(
                "POST",
                "torrents/addPeers",
                data={"hashes": infohash, "peers": peer},
            )
            _wait_for(
                lambda: bool(state.games)
                and 0 < state.games[0].completed_bytes < len(wanted)
            )
            before_cancel = int(state.games[0].completed_bytes)
            started_cancel = time.monotonic()
            stop.set()
            worker.join(timeout=3)
            assert not worker.is_alive()
            assert time.monotonic() - started_cancel < 3
            assert isinstance(first["item"], DownloadCancelled)
            cancelled_job = leech.client.info(infohash)
            assert len(cancelled_job) == 1
            assert str(cancelled_job[0]["state"]).casefold().startswith("stopped")
            assert 0 < before_cancel < len(wanted)

            stop.clear()
            seed.client._request(
                "POST",
                "torrents/setUploadLimit",
                data={"hashes": infohash, "limit": "0"},
            )
            resumed: dict[str, object] = {}
            worker = threading.Thread(target=transfer_once, args=(resumed,))
            worker.start()
            _wait_for(lambda: bool(leech.client.info(infohash)))
            leech.client._request(
                "POST",
                "torrents/addPeers",
                data={"hashes": infohash, "peers": peer},
            )
            worker.join(timeout=30)
            assert not worker.is_alive()
            prepared = resumed["item"]
            assert isinstance(prepared, PreparedTorrent)
            assert not leech.client.info(infohash)

            source = TorrentTransferSource(
                coordinator,
                source_name="legal_fixture",
                game_title="Legal fixture",
                item_id="item",
                state=state,
                state_lock=None,
                prepared=prepared,
            )
            result = download_game(
                source,
                candidate,
                target,
                None,
                "Legal fixture",
                state,
                console="fixture",
                verification_available=False,
                item_id="item",
            )

            assert result.status == "unverified"
            assert (target / "wanted.bin").read_bytes() == wanted
            assert not (target / "unwanted.bin").exists()
            assert state.games[0].outcome == "acquired"
            assert state.games[0].verification == "unverified"
        finally:
            for managed in (leech, seed):
                try:
                    managed.client.delete(infohash)
                except Exception as exc:
                    # Client exception text and tracebacks may contain API credentials.
                    logger.exception(
                        "Could not delete fixture torrent during cleanup (%s)",
                        type(exc).__name__,
                        exc_info=False,
                    )
                managed.shutdown(timeout=5)
            server.shutdown()
            server.server_close()
