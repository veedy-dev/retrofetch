from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from retrofetch.sources import SourceUnavailable
from retrofetch.sources._cloudflare_base import reset_health
from retrofetch.sources._switch_archive import candidate_for
from retrofetch.sources.romsim import RomsimSource


def test_archive_resumes_and_refuses_to_replace_existing_file(
    monkeypatch, scratch_path
) -> None:
    payload = b"authorized synthetic transfer content"
    candidate = candidate_for(
        "https://ts.bzzhr.to/d/test",
        "Example.nsp",
        "romsim",
        game_page="https://romsim.net/example/",
        host_page="https://bzzhr.to/test",
        expected_size=len(payload),
    )
    staging = scratch_path / ".retrofetch-romsim"
    staging.mkdir()
    part = staging / "Example.nsp.part"
    part.write_bytes(payload[:10])

    def respond(request: httpx.Request) -> httpx.Response:
        headers = {"Accept-Ranges": "bytes", "Content-Length": str(len(payload))}
        if request.method == "HEAD":
            return httpx.Response(200, headers=headers)
        assert request.headers.get("Range") == "bytes=10-"
        return httpx.Response(
            206,
            content=payload[10:],
            headers={"Content-Range": f"bytes 10-{len(payload) - 1}/{len(payload)}"},
        )

    client = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: client(transport=httpx.MockTransport(respond), **kwargs),
    )
    source = RomsimSource({"shortname": "switch"})
    result = source.download(candidate, scratch_path)
    assert result == scratch_path / "Example.nsp"
    assert result.read_bytes() == payload
    assert not part.exists()
    with pytest.raises(SourceUnavailable, match="overwrite"):
        source.download(candidate, scratch_path)
    assert result.read_bytes() == payload


def test_bad_size_and_symlink_never_promote_archive(monkeypatch, scratch_path) -> None:
    candidate = candidate_for(
        "https://ts.bzzhr.to/d/test",
        "Example.nsp",
        "romsim",
        game_page="https://romsim.net/example/",
        host_page="https://bzzhr.to/test",
        expected_size=100,
    )
    client = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: client(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(200, content=b"truncated")
            ),
            **kwargs,
        ),
    )
    source = RomsimSource({"shortname": "switch"})
    with pytest.raises(SourceUnavailable, match="size mismatch"):
        source.download(candidate, scratch_path)
    assert not (scratch_path / "Example.nsp").exists()

    outside = scratch_path / "keep.txt"
    outside.write_bytes(b"keep me")
    part = scratch_path / ".retrofetch-romsim" / "Example.nsp.part"
    try:
        part.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks unavailable on this platform")
    with pytest.raises(SourceUnavailable, match="not a regular file"):
        source.download(candidate, scratch_path)
    assert outside.read_bytes() == b"keep me"
    assert not (scratch_path / "Example.nsp").exists()


def test_metadata_redirect_cannot_reach_untrusted_host(monkeypatch) -> None:
    source = RomsimSource({"shortname": "switch"})
    reset_health(source.name)
    requests: list[str] = []

    def respond(_method, url, **_kwargs):
        requests.append(url)
        return SimpleNamespace(
            status_code=302,
            headers={"Location": "https://romsim.net.attacker.invalid/secret"},
            text="",
            close=lambda: None,
        )

    monkeypatch.setattr(source, "_session", SimpleNamespace(request=respond))
    monkeypatch.setattr("retrofetch.sources._switch_archive.time.sleep", lambda _: None)
    try:
        with pytest.raises(SourceUnavailable, match="unsafe URL"):
            source._get("https://romsim.net/example/")
        assert requests == ["https://romsim.net/example/"]
    finally:
        reset_health(source.name)
