from __future__ import annotations

from urllib.parse import parse_qs

import httpx

from retrofetch.qbittorrent import (
    QbittorrentClient,
    managed_paths,
    prepare_managed_profile,
)


API_KEY = "qbt_" + "A" * 28
INFOHASH = "a" * 40


def test_managed_torrents_have_no_retrofetch_download_cap(tmp_path) -> None:
    paths = managed_paths(tmp_path / "Retrofetch", platform_name="win32")
    prepare_managed_profile(paths, api_key=API_KEY, port=9191)
    profile = paths.config.read_text(encoding="utf-8")
    assert "GlobalDLSpeedLimit" not in profile
    assert "AlternativeGlobalDLSpeedLimit" not in profile

    add_form: dict[str, list[str]] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        add_form.update(parse_qs(request.content.decode("utf-8")))
        return httpx.Response(
            200,
            json={
                "added_torrent_ids": [INFOHASH],
                "success_count": 1,
                "pending_count": 0,
                "failure_count": 0,
            },
        )

    with QbittorrentClient(
        "http://127.0.0.1:8080",
        API_KEY,
        transport=httpx.MockTransport(handle),
    ) as client:
        client.add(
            f"magnet:?xt=urn:btih:{INFOHASH}",
            file_priorities=[1],
            save_path=tmp_path.resolve(),
            tag="retrofetch-performance",
        )

    assert "dlLimit" not in add_form
