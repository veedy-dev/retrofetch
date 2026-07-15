from __future__ import annotations

import base64
import hashlib
import os
from dataclasses import replace
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest

import retrofetch.qbittorrent as qb


API_KEY = "qbt_" + "A" * 28
HASH = "a" * 40
HASH_2 = "b" * 40
VALID_IDENTITY = qb.WindowsExecutableIdentity(
    product_name="qBittorrent",
    original_filename="qbittorrent.exe",
    company_name="The qBittorrent Project",
    product_version="v5.2.3",
    signature_status="NotSigned",
)


def _test_executable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    name = "qbittorrent.exe" if os.name == "nt" else "qbittorrent"
    executable = tmp_path / "bin" / name
    executable.parent.mkdir()
    executable.touch()
    if os.name == "nt":
        monkeypatch.setattr(qb, "_windows_executable_identity", lambda _: VALID_IDENTITY)
    else:
        executable.chmod(0o700)
    return executable


def _metadata(*, path: str = "PSP/Game.zip") -> dict[str, object]:
    return {
        "hash": HASH,
        "infohash_v1": HASH,
        "infohash_v2": "",
        "info": {
            "name": "PSP collection",
            "length": 12,
            "files": [{"path": path, "length": 12}],
        },
    }


def _client(handler: httpx.MockTransport) -> qb.QbittorrentClient:
    return qb.QbittorrentClient(
        "http://127.0.0.1:8080", API_KEY, transport=handler
    )


def test_loopback_url_is_strict() -> None:
    assert qb.validate_loopback_url("http://localhost:8080/") == "http://localhost:8080"
    assert qb.validate_loopback_url("http://[::1]:8080") == "http://[::1]:8080"
    for value in (
        "http://example.com:8080",
        "http://127.0.0.1:8080/api",
        "http://user:pass@127.0.0.1:8080",
        "http://local.test:8080",
        "http://127.0.0.1",
    ):
        with pytest.raises(qb.QbittorrentSecurityError):
            qb.validate_loopback_url(value)


def test_versions_readiness_preferences_and_bearer_header() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == f"Bearer {API_KEY}"
        assert request.headers["Origin"] == "http://127.0.0.1:8080"
        values: dict[str, object] = {
            "/api/v2/app/version": "v5.2.3",
            "/api/v2/app/webapiVersion": "2.14.1",
            "/api/v2/app/preferences": {"web_ui_address": "127.0.0.1"},
        }
        value = values[request.url.path]
        if isinstance(value, dict):
            return httpx.Response(200, json=value)
        assert isinstance(value, str)
        return httpx.Response(200, text=value)

    with _client(httpx.MockTransport(handle)) as client:
        assert client.assert_ready() == qb.VersionInfo("v5.2.3", "2.14.1")
        assert client.preferences()["web_ui_address"] == "127.0.0.1"
        assert API_KEY not in repr(client)


def test_process_launch_time_is_strict() -> None:
    with _client(
        httpx.MockTransport(
            lambda _: httpx.Response(200, json={"launch_time": 1_725_000_000})
        )
    ) as client:
        assert client.process_launch_time() == 1_725_000_000

    with _client(
        httpx.MockTransport(
            lambda _: httpx.Response(200, json={"launch_time": "yesterday"})
        )
    ) as client:
        with pytest.raises(qb.QbittorrentProtocolError, match="process identity"):
            client.process_launch_time()


def test_readiness_rejects_unsupported_versions() -> None:
    responses = iter(["v5.1.9", "2.14.1"])
    client = _client(httpx.MockTransport(lambda _: httpx.Response(200, text=next(responses))))
    with client, pytest.raises(qb.QbittorrentVersionError, match="5.2.x"):
        client.assert_ready()


def test_errors_are_classified_and_redacted() -> None:
    client = _client(
        httpx.MockTransport(
            lambda _: httpx.Response(401, text=f"Authorization: Bearer {API_KEY}")
        )
    )
    with client, pytest.raises(qb.QbittorrentAuthError) as exc:
        client.preferences()
    assert API_KEY not in str(exc.value)
    assert "<redacted>" in str(exc.value)


def test_fetch_and_parse_metadata() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("fetchMetadata"):
            assert request.method == "POST"
            assert parse_qs(request.content.decode())["source"] == ["magnet:?xt=urn:btih:test"]
            return httpx.Response(200, json=_metadata())
        assert request.url.path.endswith("parseMetadata")
        assert request.method == "POST"
        assert "multipart/form-data" in request.headers["content-type"]
        return httpx.Response(200, json=[_metadata()])

    with _client(httpx.MockTransport(handle)) as client:
        fetched = client.fetch_metadata("magnet:?xt=urn:btih:test")
        parsed = client.parse_metadata(b"torrent", filename="game.torrent")
    assert fetched == parsed
    assert fetched.files == (qb.TorrentMetadataFile(0, "PSP/Game.zip", 12),)
    assert fetched.total_size == 12


@pytest.mark.parametrize(
    "path",
    [
        "../escape.zip",
        "folder\\..\\escape.zip",
        "CON.zip",
        "folder./game.zip",
        "bad:name.zip",
        "/".join(["folder"] * 32 + ["game.zip"]),
    ],
)
def test_fetch_metadata_reports_pending_and_rejects_unsafe_paths(path: str) -> None:
    pending = {"hash": HASH, "infohash_v1": HASH, "infohash_v2": ""}
    client = _client(httpx.MockTransport(lambda _: httpx.Response(202, json=pending)))
    with client:
        assert client.fetch_metadata(HASH).pending is True

    client = _client(
        httpx.MockTransport(lambda _: httpx.Response(200, json=_metadata(path=path)))
    )
    with client, pytest.raises(qb.QbittorrentProtocolError, match="file path"):
        client.fetch_metadata(HASH)


def test_metadata_allows_unrelated_windows_case_collisions() -> None:
    payload = _metadata()
    info = payload["info"]
    assert isinstance(info, dict)
    info["length"] = 24
    info["files"] = [
        {"path": "PSP/Game.zip", "length": 12},
        {"path": "psp/game.ZIP", "length": 12},
    ]
    client = _client(httpx.MockTransport(lambda _: httpx.Response(200, json=payload)))
    with client:
        metadata = client.fetch_metadata(HASH)
    assert len(metadata.files) == 2


def test_files_can_request_only_selected_indexes() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.params["hash"] == HASH
        assert request.url.params["indexes"] == "1|3"
        return httpx.Response(200, json=[{"index": 1}, {"index": 3}])

    with _client(httpx.MockTransport(handle)) as client:
        assert [entry["index"] for entry in client.files(HASH, indexes=[1, 3])] == [
            1,
            3,
        ]
        with pytest.raises(ValueError, match="non-negative"):
            client.files(HASH, indexes=[])


def test_http_metadata_pending_response_may_be_empty() -> None:
    client = _client(httpx.MockTransport(lambda _: httpx.Response(202, json={})))
    with client:
        metadata = client.fetch_metadata("https://example.test/file.torrent")
    assert metadata.pending is True
    assert metadata.torrent_id is None


def test_add_and_torrent_operations_use_safe_contract(tmp_path: Path) -> None:
    calls: list[tuple[str, dict[str, list[str]]]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        form = parse_qs(request.content.decode()) if request.method == "POST" else {}
        calls.append((request.url.path, form))
        if request.url.path.endswith("/add"):
            return httpx.Response(
                200,
                json={
                    "added_torrent_ids": [HASH],
                    "success_count": 1,
                    "pending_count": 0,
                    "failure_count": 0,
                },
            )
        if request.url.path.endswith("/info"):
            return httpx.Response(200, json=[{"hash": HASH, "state": "stoppedDL"}])
        if request.url.path.endswith("/files"):
            return httpx.Response(200, json=[{"index": 0, "name": "PSP/Game.zip"}])
        return httpx.Response(204)

    with _client(httpx.MockTransport(handle)) as client:
        result = client.add(
            HASH,
            file_priorities=[0, 1],
            save_path=tmp_path,
            tag="retrofetch-run",
        )
        assert client.info(HASH, tag="retrofetch-run")[0]["hash"] == HASH
        assert client.files(HASH)[0]["index"] == 0
        client.set_file_priority(HASH, [0, 1], 0)
        client.start([HASH, HASH_2])
        client.stop(HASH)
        client.set_share_limits(HASH)
        client.delete(HASH)
        client.shutdown()

    assert result == qb.AddResult((HASH,), 1, 0, 0)
    add = calls[0][1]
    assert add["filePriorities"] == ["0,1"]
    assert add["stopped"] == ["true"]
    assert add["autoTMM"] == ["false"]
    assert add["shareLimitAction"] == ["Stop"]
    assert calls[3][1]["id"] == ["0|1"]
    assert calls[4][1]["hashes"] == [f"{HASH}|{HASH_2}"]
    assert calls[6][1]["shareLimitAction"] == ["Stop"]
    assert calls[7][1]["deleteFiles"] == ["false"]


def test_metadata_fetch_and_add_share_qbittorrents_decoded_cache_key(
    tmp_path: Path,
) -> None:
    sources: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        form = parse_qs(request.content.decode())
        if request.url.path.endswith("/fetchMetadata"):
            sources.append(form["source"][0])
            return httpx.Response(
                200,
                json={
                    "hash": HASH,
                    "infohash_v1": HASH,
                    "info": {
                        "name": "Collection",
                        "length": 1,
                        "files": [
                            {"path": "Collection/Game.zip", "length": 1}
                        ],
                    },
                },
            )
        sources.append(form["urls"][0])
        return httpx.Response(
            200,
            json={
                "added_torrent_ids": [HASH],
                "success_count": 1,
                "pending_count": 0,
                "failure_count": 0,
            },
        )

    encoded = "https://example.test/Collection%20One.torrent"
    with _client(httpx.MockTransport(handle)) as client:
        client.fetch_metadata(encoded)
        client.add(
            encoded,
            file_priorities=[1],
            save_path=tmp_path,
            tag="retrofetch-run",
        )

    assert sources == [
        "https://example.test/Collection One.torrent",
        "https://example.test/Collection One.torrent",
    ]
    with _client(httpx.MockTransport(handle)) as client:
        with pytest.raises(ValueError, match="one non-empty"):
            client.fetch_metadata("https://example.test/a%0Ab.torrent")


def test_managed_paths_profile_and_commands_are_pinned(tmp_path: Path) -> None:
    paths = qb.managed_paths(tmp_path / "Retrofetch", platform_name="win32")
    qb.prepare_managed_profile(paths, api_key=API_KEY, port=9191)
    config = paths.config.read_text(encoding="utf-8")
    assert paths.config == (
        tmp_path
        / "Retrofetch"
        / "qbittorrent"
        / "profile"
        / "qBittorrent_retrofetch"
        / "config"
        / "qBittorrent.ini"
    )
    assert "WebUI\\Address=127.0.0.1" in config
    assert "PortForwardingEnabled=false" in config
    assert "Session\\PortForwardingEnabled=false" in config
    assert "Session\\ShareLimitAction=Stop" in config
    assert f"WebUI\\APIKey={API_KEY}" in config
    assert "StartUpWindowState=Minimized" in config
    assert "WebUI\\Username=retrofetch_" in config
    assert 'WebUI\\Password_PBKDF2="@ByteArray(' in config
    show = qb.winget_show_command()
    install = qb.winget_install_command()
    assert show[:4] == ("winget", "show", "--id", qb.QBITTORRENT_PACKAGE_ID)
    assert qb.QBITTORRENT_VERSION in show
    assert install[:4] == ("winget", "install", "--id", qb.QBITTORRENT_PACKAGE_ID)
    assert "--silent" in install
    assert "--accept-package-agreements" in install

    posix = qb.managed_paths(tmp_path / "retrofetch", platform_name="linux")
    assert posix.config.name == "qBittorrent.conf"


def test_webui_basic_hash_matches_qbittorrent_pbkdf2(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    material = bytes(range(56))
    monkeypatch.setattr(qb.secrets, "token_bytes", lambda size: material[:size])

    username, qsettings_value = qb._webui_basic_credentials()

    password = base64.urlsafe_b64encode(material[8:40])
    salt = material[40:56]
    digest = hashlib.pbkdf2_hmac("sha512", password, salt, 100_000, dklen=64)
    secret = base64.b64encode(salt) + b":" + base64.b64encode(digest)
    assert username == "retrofetch_0001020304050607"
    assert qsettings_value == f'"@ByteArray({secret.decode("ascii")})"'


def test_windows_executable_identity_uses_fixed_powershell_and_literal_env_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executable = tmp_path / "qbittorrent.exe"
    executable.touch()
    powershell = tmp_path / "powershell.exe"
    powershell.touch()
    captured: dict[str, object] = {}

    def run(command, **kwargs):
        captured["command"] = command
        captured["env"] = kwargs["env"]
        return qb.subprocess.CompletedProcess(
            command,
            0,
            stdout=(
                '{"product_name":"qBittorrent","original_filename":"qbittorrent.exe",'
                '"company_name":"The qBittorrent Project","product_version":"v5.2.3",'
                '"signature_status":"NotSigned"}'
            ),
            stderr="",
        )

    monkeypatch.setattr(qb, "_powershell_executable", lambda: powershell)
    monkeypatch.setattr(qb.subprocess, "run", run)

    assert qb._windows_executable_identity(executable) == VALID_IDENTITY
    command = captured["command"]
    environment = captured["env"]
    assert isinstance(command, list) and command[0] == str(powershell)
    assert isinstance(environment, dict)
    assert environment["RETROFETCH_QB_IDENTITY_PATH"] == str(executable)
    assert str(executable) not in command


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("product_name", "Not qBittorrent"),
        ("original_filename", "other.exe"),
        ("company_name", "Other Publisher"),
        ("product_version", "v5.2.2"),
        ("signature_status", "HashMismatch"),
    ],
)
def test_windows_executable_identity_rejects_mismatches(field: str, value: str) -> None:
    with pytest.raises(qb.QbittorrentSecurityError, match="pinned 5.2.3"):
        qb._validate_windows_executable_identity(replace(VALID_IDENTITY, **{field: value}))


def test_windows_executable_identity_accepts_unsigned_or_valid_signature() -> None:
    qb._validate_windows_executable_identity(VALID_IDENTITY)
    qb._validate_windows_executable_identity(
        replace(
            VALID_IDENTITY,
            company_name="THE QBITTORRENT PROJECT",
            signature_status="Valid",
        )
    )


def test_discovery_never_uses_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(qb, "_windows_executable_identity", lambda _: VALID_IDENTITY)
    arbitrary = tmp_path / "path" / "qbittorrent.exe"
    arbitrary.parent.mkdir()
    arbitrary.touch()
    assert (
        qb.discover_qbittorrent(
            environ={"PATH": str(arbitrary.parent)}, platform_name="win32"
        )
        is None
    )

    known = tmp_path / "qBittorrent" / "qbittorrent.exe"
    known.parent.mkdir()
    known.touch()
    assert qb.discover_qbittorrent(
        environ={"ProgramFiles": str(tmp_path)}, platform_name="win32"
    ) == known.resolve()
    assert qb.discover_qbittorrent(known, platform_name="win32") == known.resolve()


@pytest.mark.parametrize(
    ("platform_name", "parts"),
    [
        ("linux", (".local", "bin", "qbittorrent")),
        (
            "darwin",
            ("Applications", "qBittorrent.app", "Contents", "MacOS", "qbittorrent"),
        ),
    ],
)
def test_posix_discovery_uses_known_user_install_locations(
    tmp_path: Path, platform_name: str, parts: tuple[str, ...]
) -> None:
    executable = tmp_path.joinpath(*parts)
    executable.parent.mkdir(parents=True)
    executable.touch()
    executable.chmod(0o700)

    assert qb.discover_qbittorrent(
        platform_name=platform_name, home=tmp_path
    ) == executable.resolve()


def test_exclusive_lock_rejects_second_owner(tmp_path: Path) -> None:
    first = qb.ExclusiveFileLock(tmp_path / "runtime.lock")
    second = qb.ExclusiveFileLock(tmp_path / "runtime.lock")
    first.acquire()
    try:
        with pytest.raises(qb.QbittorrentBusy):
            second.acquire()
    finally:
        first.release()
    second.acquire()
    second.release()


def test_start_and_shutdown_managed_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executable = _test_executable(tmp_path, monkeypatch)
    paths = qb.managed_paths(tmp_path)
    commands: list[tuple[str, ...]] = []

    class FakeProcess:
        def __init__(self, command: tuple[str, ...], **_: object) -> None:
            commands.append(command)
            self.running = True

        def poll(self) -> int | None:
            return None if self.running else 0

        def wait(self, *, timeout: float) -> int:
            self.running = False
            return 0

        def terminate(self) -> None:
            self.running = False

        def kill(self) -> None:
            self.running = False

    monkeypatch.setattr(qb.subprocess, "Popen", FakeProcess)

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("app/version"):
            return httpx.Response(200, text="v5.2.3")
        if request.url.path.endswith("app/webapiVersion"):
            return httpx.Response(200, text="2.14.1")
        return httpx.Response(204)

    managed = qb.start_managed(
        executable,
        paths,
        api_key=API_KEY,
        port=9191,
        legal_notice_accepted=True,
        transport=httpx.MockTransport(handle),
    )
    managed.shutdown()
    assert commands[0][0] == str(executable.resolve())
    assert f"--profile={paths.profile}" in commands[0]
    assert "--confirm-legal-notice" in commands[0]
    assert managed._closed is True


def test_managed_command_requires_explicit_legal_acceptance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executable = _test_executable(tmp_path, monkeypatch)
    paths = qb.managed_paths(tmp_path)
    with pytest.raises(qb.QbittorrentSecurityError, match="legal notice"):
        qb.start_managed(
            executable,
            paths,
            api_key=API_KEY,
            port=8080,
            legal_notice_accepted=False,
        )
    assert not paths.root.exists()
