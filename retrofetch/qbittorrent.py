from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import os
import re
import secrets
import string
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Mapping, Sequence
from urllib.parse import unquote, urlsplit, urlunsplit

import httpx

from retrofetch.config import user_config_dir


QBITTORRENT_PACKAGE_ID = "qBittorrent.qBittorrent"
QBITTORRENT_VERSION = "5.2.3"
QBITTORRENT_PUBLISHER = "The qBittorrent project"
QBITTORRENT_INSTALLER_URL = (
    "https://sourceforge.net/projects/qbittorrent/files/qbittorrent-win32/"
    "qbittorrent-5.2.3/qbittorrent_5.2.3_x64_setup.exe/download"
)
QBITTORRENT_INSTALLER_SHA256 = (
    "ff508e2f912d59c9eabaf03633ebacfd45c2049f38dcac027b8a7d7ad867ab2f"
)
QBITTORRENT_DOWNLOAD_URL = "https://www.qbittorrent.org/download"
QBITTORRENT_LINUX_APPIMAGES = {
    "qbittorrent-5.2.3_x86_64.AppImage": (
        "c1467a713929323aaf253e021449992ac299a6c830a933643b023007d8641ed0"
    ),
    "qbittorrent-5.2.3_lt20_x86_64.AppImage": (
        "71b3a861753674d941e517feff72ed47d1a0e5c01a0a39e9c3d7f7ccc3f80c63"
    ),
}
MIN_WEB_API_VERSION = (2, 14, 1)
MAX_METADATA_BYTES = 32 * 1024 * 1024
MAX_METADATA_FILES = 50_000
MAX_TORRENT_BYTES = 100 * 1024**4

_API_KEY_RE = re.compile(r"^qbt_[A-Za-z0-9]{28}$")
_HASH_RE = re.compile(r"^(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})$")
_VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)(?:\.(\d+))?")
_SECRET_RE = re.compile(
    r"(?i)(?:Bearer\s+)?qbt_[A-Za-z0-9]{28}|"
    r"(authorization\s*[:=]\s*)([^\s,;]+)"
)
_WINDOWS_RESERVED_NAMES = {
    "aux",
    "con",
    "nul",
    "prn",
    *(f"com{number}" for number in range(1, 10)),
    *(f"lpt{number}" for number in range(1, 10)),
}
_WINDOWS_INVALID_CHARS = frozenset('<>:"|?*')


class QbittorrentError(RuntimeError):
    """Base error for the local qBittorrent integration."""


class QbittorrentSecurityError(QbittorrentError):
    """Raised when a local-only or ownership boundary is violated."""


class QbittorrentUnavailable(QbittorrentError):
    """Raised when the local qBittorrent API cannot be reached."""


class QbittorrentAuthError(QbittorrentError):
    """Raised when the configured API key is rejected."""


class QbittorrentVersionError(QbittorrentError):
    """Raised when qBittorrent or its Web API is unsupported."""


class QbittorrentNotFound(QbittorrentError):
    """Raised when an owned torrent no longer exists."""


class QbittorrentProtocolError(QbittorrentError):
    """Raised for an invalid response or request contract."""


class QbittorrentBusy(QbittorrentError):
    """Raised when another Retrofetch process owns the managed runtime."""


def redact(value: object) -> str:
    """Remove qBittorrent API keys and authorization values from diagnostics."""

    text = str(value)

    def replace(match: re.Match[str]) -> str:
        prefix = match.group(1) or ""
        return f"{prefix}<redacted>"

    return _SECRET_RE.sub(replace, text)


def validate_loopback_url(value: str) -> str:
    """Return a normalized local Web API URL or fail closed."""

    parts = urlsplit(value.strip())
    if parts.scheme not in {"http", "https"}:
        raise QbittorrentSecurityError("qBittorrent URL must use http or https")
    if parts.username or parts.password:
        raise QbittorrentSecurityError("qBittorrent credentials cannot be in the URL")
    if parts.path not in {"", "/"} or parts.query or parts.fragment:
        raise QbittorrentSecurityError("qBittorrent URL must not contain a path, query, or fragment")
    host = parts.hostname
    if not host:
        raise QbittorrentSecurityError("qBittorrent URL is missing a host")
    if host.casefold() != "localhost":
        try:
            if not ipaddress.ip_address(host).is_loopback:
                raise QbittorrentSecurityError("qBittorrent URL must be loopback-only")
        except ValueError as exc:
            raise QbittorrentSecurityError(
                "qBittorrent URL must use localhost or a loopback IP literal"
            ) from exc
    try:
        port = parts.port
    except ValueError as exc:
        raise QbittorrentSecurityError("qBittorrent URL has an invalid port") from exc
    if port is None:
        raise QbittorrentSecurityError("qBittorrent URL must include its local port")
    netloc = f"[{host}]:{port}" if ":" in host else f"{host}:{port}"
    return urlunsplit((parts.scheme, netloc, "", "", ""))


@dataclass(frozen=True)
class VersionInfo:
    application: str
    web_api: str


@dataclass(frozen=True)
class TorrentMetadataFile:
    index: int
    path: str
    length: int


@dataclass(frozen=True)
class TorrentMetadata:
    torrent_id: str | None
    infohash_v1: str | None
    infohash_v2: str | None
    name: str | None
    files: tuple[TorrentMetadataFile, ...]
    total_size: int | None
    pending: bool = False


@dataclass(frozen=True)
class AddResult:
    torrent_ids: tuple[str, ...]
    success_count: int
    pending_count: int
    failure_count: int


def _version(value: str) -> tuple[int, int, int]:
    match = _VERSION_RE.match(value.strip())
    if not match:
        raise QbittorrentVersionError(f"invalid qBittorrent version: {redact(value)}")
    return int(match.group(1)), int(match.group(2)), int(match.group(3) or 0)


def _torrent_id(value: object) -> str:
    if not isinstance(value, str) or not _HASH_RE.fullmatch(value):
        raise QbittorrentProtocolError("qBittorrent returned an invalid torrent id")
    return value.lower()


def _torrent_ids(values: str | Sequence[str]) -> str:
    items = [values] if isinstance(values, str) else list(values)
    if not items:
        raise ValueError("at least one torrent id is required")
    return "|".join(_torrent_id(value) for value in items)


def _tag(value: str) -> str:
    value = value.strip()
    if not value or any(char in value for char in ",\r\n"):
        raise ValueError("qBittorrent tag must be non-empty and contain no comma or newline")
    return value


def _metadata_source(value: str) -> str:
    """Match qBittorrent's decoded metadata-cache key for fetch then add."""

    decoded = unquote(value)
    if not decoded.strip() or any(char in decoded for char in "\r\n"):
        raise ValueError("torrent source must be one non-empty URI or hash")
    return decoded


def _safe_metadata_path(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or "\x00" in value
        or "\\" in value
        or len(value) > 4096
    ):
        raise QbittorrentProtocolError("torrent metadata contains an invalid file path")
    path = PurePosixPath(value)
    windows_path = PureWindowsPath(value)
    if (
        path.is_absolute()
        or windows_path.is_absolute()
        or windows_path.drive
        or len(path.parts) > 32
        or any(
            part in {"", ".", ".."}
            or len(part) > 255
            or part.endswith((".", " "))
            or part.split(".", 1)[0].casefold() in _WINDOWS_RESERVED_NAMES
            or any(char in _WINDOWS_INVALID_CHARS or ord(char) < 32 for char in part)
            for part in path.parts
        )
    ):
        raise QbittorrentProtocolError("torrent metadata contains an unsafe file path")
    return path.as_posix()


def _parse_metadata(payload: object, *, pending: bool = False) -> TorrentMetadata:
    if not isinstance(payload, dict):
        raise QbittorrentProtocolError("qBittorrent returned invalid torrent metadata")
    if not payload and pending:
        return TorrentMetadata(None, None, None, None, (), None, True)
    v1 = payload.get("infohash_v1") or None
    v2 = payload.get("infohash_v2") or None
    if v1 is not None:
        v1 = _torrent_id(v1)
    if v2 is not None:
        v2 = _torrent_id(v2)
    raw_id = payload.get("hash") or payload.get("id") or v1 or v2
    if raw_id is None:
        raise QbittorrentProtocolError("qBittorrent metadata has no torrent hash")
    torrent_id = _torrent_id(raw_id)
    raw_info = payload.get("info")
    if raw_info is None:
        if pending:
            return TorrentMetadata(torrent_id, v1, v2, None, (), None, True)
        raise QbittorrentProtocolError("qBittorrent returned incomplete torrent metadata")
    if not isinstance(raw_info, dict):
        raise QbittorrentProtocolError("qBittorrent returned invalid torrent info")
    name = raw_info.get("name")
    raw_files = raw_info.get("files")
    if not isinstance(name, str) or not name or not isinstance(raw_files, list):
        raise QbittorrentProtocolError("qBittorrent returned incomplete torrent info")
    if len(raw_files) > MAX_METADATA_FILES:
        raise QbittorrentProtocolError("torrent metadata contains too many files")
    files: list[TorrentMetadataFile] = []
    total = 0
    for index, item in enumerate(raw_files):
        if not isinstance(item, dict):
            raise QbittorrentProtocolError("qBittorrent returned invalid file metadata")
        length = item.get("length")
        if not isinstance(length, int) or isinstance(length, bool) or length < 0:
            raise QbittorrentProtocolError("torrent metadata contains an invalid file size")
        total += length
        if total > MAX_TORRENT_BYTES:
            raise QbittorrentProtocolError("torrent metadata declares too much data")
        path = _safe_metadata_path(item.get("path"))
        files.append(TorrentMetadataFile(index, path, length))
    declared_total = raw_info.get("length")
    if declared_total is not None and declared_total != total:
        raise QbittorrentProtocolError("torrent metadata size does not match its files")
    return TorrentMetadata(torrent_id, v1, v2, name, tuple(files), total, pending)


class QbittorrentClient:
    """Small qBittorrent 5.2.x Web API client using Bearer API-key auth."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout: float = 10.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = validate_loopback_url(base_url)
        if not _API_KEY_RE.fullmatch(api_key):
            raise QbittorrentAuthError("qBittorrent API key has an invalid format")
        self._client = httpx.Client(
            base_url=f"{self.base_url}/api/v2/",
            headers={"Authorization": f"Bearer {api_key}", "Origin": self.base_url},
            timeout=timeout,
            transport=transport,
            follow_redirects=False,
            trust_env=False,
        )

    def __enter__(self) -> QbittorrentClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"QbittorrentClient(base_url={self.base_url!r})"

    def close(self) -> None:
        self._client.close()

    def _request(
        self,
        method: str,
        endpoint: str,
        *,
        expected: tuple[int, ...] = (200, 204),
        **kwargs: Any,
    ) -> httpx.Response:
        try:
            response = self._client.request(method, endpoint, **kwargs)
        except httpx.TimeoutException as exc:
            raise QbittorrentUnavailable("qBittorrent API timed out") from exc
        except httpx.RequestError as exc:
            raise QbittorrentUnavailable(
                f"qBittorrent API is unavailable: {redact(exc)}"
            ) from exc
        if response.status_code in expected:
            return response
        detail = redact(response.text[:500]).strip() or "request failed"
        message = f"qBittorrent API {response.status_code}: {detail}"
        if response.status_code in {401, 403}:
            raise QbittorrentAuthError(message)
        if response.status_code == 404:
            raise QbittorrentNotFound(message)
        if response.status_code >= 500:
            raise QbittorrentUnavailable(message)
        raise QbittorrentProtocolError(message)

    @staticmethod
    def _json(response: httpx.Response) -> object:
        try:
            return response.json()
        except ValueError as exc:
            raise QbittorrentProtocolError("qBittorrent returned invalid JSON") from exc

    def versions(self) -> VersionInfo:
        application = self._request("GET", "app/version").text.strip()
        web_api = self._request("GET", "app/webapiVersion").text.strip()
        _version(application)
        _version(web_api)
        return VersionInfo(application, web_api)

    def assert_ready(self) -> VersionInfo:
        versions = self.versions()
        app = _version(versions.application)
        api = _version(versions.web_api)
        if app[:2] != (5, 2):
            raise QbittorrentVersionError(
                f"qBittorrent 5.2.x is required; found {versions.application}"
            )
        if api < MIN_WEB_API_VERSION:
            required = ".".join(str(part) for part in MIN_WEB_API_VERSION)
            raise QbittorrentVersionError(
                f"qBittorrent Web API >= {required} is required; found {versions.web_api}"
            )
        return versions

    def wait_ready(
        self,
        *,
        timeout: float = 20.0,
        poll_interval: float = 0.25,
        process: subprocess.Popen[bytes] | None = None,
        stop_event: threading.Event | None = None,
    ) -> VersionInfo:
        deadline = time.monotonic() + timeout
        while True:
            if process is not None and process.poll() is not None:
                raise QbittorrentUnavailable("managed qBittorrent exited before becoming ready")
            if stop_event is not None and stop_event.is_set():
                raise QbittorrentUnavailable("managed qBittorrent startup was cancelled")
            try:
                return self.assert_ready()
            except QbittorrentUnavailable:
                if time.monotonic() >= deadline:
                    raise QbittorrentUnavailable(
                        "managed qBittorrent did not become ready in time"
                    ) from None
                delay = min(poll_interval, max(0.0, deadline - time.monotonic()))
                if stop_event is not None:
                    stop_event.wait(delay)
                else:
                    time.sleep(delay)

    def preferences(self) -> dict[str, Any]:
        payload = self._json(self._request("GET", "app/preferences"))
        if not isinstance(payload, dict):
            raise QbittorrentProtocolError("qBittorrent returned invalid preferences")
        return payload

    def process_launch_time(self) -> int:
        """Return the managed qB process identity exposed by Web API 2.15.1+."""

        payload = self._json(self._request("GET", "app/processInfo"))
        launch_time = payload.get("launch_time") if isinstance(payload, dict) else None
        if (
            not isinstance(launch_time, int)
            or isinstance(launch_time, bool)
            or launch_time <= 0
        ):
            raise QbittorrentProtocolError(
                "qBittorrent returned invalid process identity"
            )
        return launch_time

    def fetch_metadata(self, source: str) -> TorrentMetadata:
        response = self._request(
            "POST",
            "torrents/fetchMetadata",
            data={"source": _metadata_source(source)},
            expected=(200, 202),
        )
        return _parse_metadata(self._json(response), pending=response.status_code == 202)

    def parse_metadata(
        self, content: bytes, *, filename: str = "metadata.torrent"
    ) -> TorrentMetadata:
        if not content or len(content) > MAX_METADATA_BYTES:
            raise ValueError("torrent metadata must be between 1 byte and 32 MiB")
        safe_name = Path(filename).name
        if safe_name != filename or not safe_name.casefold().endswith(".torrent"):
            raise ValueError("torrent metadata filename must be a simple .torrent name")
        response = self._request(
            "POST",
            "torrents/parseMetadata",
            files={"file": (safe_name, content, "application/x-bittorrent")},
        )
        payload = self._json(response)
        if not isinstance(payload, list) or len(payload) != 1:
            raise QbittorrentProtocolError("qBittorrent returned invalid parsed metadata")
        return _parse_metadata(payload[0])

    def add(
        self,
        source: str,
        *,
        file_priorities: Sequence[int],
        save_path: Path,
        tag: str,
        stopped: bool = True,
    ) -> AddResult:
        priorities = list(file_priorities)
        if not priorities or any(priority not in {0, 1, 6, 7} for priority in priorities):
            raise ValueError("file priorities must use qBittorrent values 0, 1, 6, or 7")
        if not save_path.is_absolute():
            raise ValueError("qBittorrent save path must be absolute")
        response = self._request(
            "POST",
            "torrents/add",
            expected=(200, 202),
            data={
                "urls": _metadata_source(source),
                "filePriorities": ",".join(str(priority) for priority in priorities),
                "savepath": str(save_path),
                "tags": _tag(tag),
                "stopped": str(stopped).lower(),
                "autoTMM": "false",
                "ratioLimit": "0",
                "seedingTimeLimit": "0",
                "inactiveSeedingTimeLimit": "0",
                "shareLimitAction": "Stop",
            },
        )
        payload = self._json(response)
        if not isinstance(payload, dict):
            raise QbittorrentProtocolError("qBittorrent returned an invalid add result")
        ids = payload.get("added_torrent_ids")
        success_count = payload.get("success_count")
        pending_count = payload.get("pending_count")
        failure_count = payload.get("failure_count")
        counts = (success_count, pending_count, failure_count)
        if (
            not isinstance(ids, list)
            or any(not isinstance(count, int) or isinstance(count, bool) or count < 0 for count in counts)
        ):
            raise QbittorrentProtocolError("qBittorrent returned an invalid add result")
        assert isinstance(success_count, int)
        assert isinstance(pending_count, int)
        assert isinstance(failure_count, int)
        return AddResult(
            tuple(_torrent_id(item) for item in ids),
            success_count,
            pending_count,
            failure_count,
        )

    def info(
        self, torrent_id: str | None = None, *, tag: str | None = None
    ) -> tuple[dict[str, Any], ...]:
        params: dict[str, str] = {}
        if torrent_id is not None:
            params["hashes"] = _torrent_id(torrent_id)
        if tag is not None:
            params["tag"] = _tag(tag)
        payload = self._json(self._request("GET", "torrents/info", params=params))
        if not isinstance(payload, list) or any(not isinstance(item, dict) for item in payload):
            raise QbittorrentProtocolError("qBittorrent returned an invalid torrent list")
        return tuple(payload)

    def files(
        self, torrent_id: str, *, indexes: Sequence[int] | None = None
    ) -> tuple[dict[str, Any], ...]:
        params = {"hash": _torrent_id(torrent_id)}
        if indexes is not None:
            values = list(indexes)
            if not values or any(
                not isinstance(index, int) or isinstance(index, bool) or index < 0
                for index in values
            ):
                raise ValueError("qBittorrent file indexes must be non-negative integers")
            params["indexes"] = "|".join(str(index) for index in values)
        payload = self._json(
            self._request("GET", "torrents/files", params=params)
        )
        if not isinstance(payload, list) or any(not isinstance(item, dict) for item in payload):
            raise QbittorrentProtocolError("qBittorrent returned an invalid file list")
        return tuple(payload)

    def set_file_priority(
        self,
        torrent_id: str,
        indexes: int | Sequence[int],
        priority: int,
    ) -> None:
        values = [indexes] if isinstance(indexes, int) else list(indexes)
        if not values or any(
            not isinstance(index, int) or isinstance(index, bool) or index < 0
            for index in values
        ):
            raise ValueError("qBittorrent file indexes must be non-negative integers")
        if priority not in {0, 1, 6, 7}:
            raise ValueError("invalid qBittorrent file priority")
        self._request(
            "POST",
            "torrents/filePrio",
            data={
                "hash": _torrent_id(torrent_id),
                "id": "|".join(str(index) for index in values),
                "priority": str(priority),
            },
        )

    def start(self, torrent_ids: str | Sequence[str]) -> None:
        self._request("POST", "torrents/start", data={"hashes": _torrent_ids(torrent_ids)})

    def stop(self, torrent_ids: str | Sequence[str]) -> None:
        self._request("POST", "torrents/stop", data={"hashes": _torrent_ids(torrent_ids)})

    def set_share_limits(
        self,
        torrent_ids: str | Sequence[str],
        *,
        ratio_limit: float = 0.0,
        seeding_time_limit: int = 0,
        inactive_seeding_time_limit: int = 0,
    ) -> None:
        if ratio_limit < 0 or seeding_time_limit < 0 or inactive_seeding_time_limit < 0:
            raise ValueError("Retrofetch share limits cannot allow unbounded seeding")
        self._request(
            "POST",
            "torrents/setShareLimits",
            data={
                "hashes": _torrent_ids(torrent_ids),
                "ratioLimit": str(ratio_limit),
                "seedingTimeLimit": str(seeding_time_limit),
                "inactiveSeedingTimeLimit": str(inactive_seeding_time_limit),
                "shareLimitAction": "Stop",
            },
        )

    def delete(self, torrent_ids: str | Sequence[str]) -> None:
        self._request(
            "POST",
            "torrents/delete",
            data={"hashes": _torrent_ids(torrent_ids), "deleteFiles": "false"},
        )

    def shutdown(self) -> None:
        self._request("POST", "app/shutdown")


@dataclass(frozen=True)
class ManagedPaths:
    root: Path
    profile: Path
    config: Path
    lock: Path


@dataclass(frozen=True)
class WindowsExecutableIdentity:
    product_name: str
    original_filename: str
    company_name: str
    product_version: str
    signature_status: str


def managed_paths(
    app_dir: str | Path | None = None, *, platform_name: str | None = None
) -> ManagedPaths:
    base = Path(app_dir).expanduser() if app_dir is not None else user_config_dir()
    if not base.is_absolute():
        raise QbittorrentSecurityError("Retrofetch app data path must be absolute")
    root = base / "qbittorrent"
    profile = root / "profile"
    platform_name = sys.platform if platform_name is None else platform_name
    config_name = "qBittorrent.ini" if platform_name.startswith("win") else "qBittorrent.conf"
    config = profile / "qBittorrent_retrofetch" / "config" / config_name
    return ManagedPaths(root, profile, config, root / "managed.lock")


def generate_api_key() -> str:
    alphabet = string.ascii_letters + string.digits
    return "qbt_" + "".join(secrets.choice(alphabet) for _ in range(28))


def _webui_basic_credentials() -> tuple[str, str]:
    """Create throwaway Basic credentials required for qB's WebUI to start."""

    material = secrets.token_bytes(56)
    username = f"retrofetch_{material[:8].hex()}"
    password = base64.urlsafe_b64encode(material[8:40])
    salt = material[40:56]
    digest = hashlib.pbkdf2_hmac("sha512", password, salt, 100_000, dklen=64)
    secret = base64.b64encode(salt) + b":" + base64.b64encode(digest)
    return username, f'"@ByteArray({secret.decode("ascii")})"'


def prepare_managed_profile(paths: ManagedPaths, *, api_key: str, port: int) -> None:
    _validate_managed_paths(paths)
    if not _API_KEY_RE.fullmatch(api_key):
        raise QbittorrentAuthError("qBittorrent API key has an invalid format")
    if not 1 <= port <= 65535:
        raise ValueError("qBittorrent Web API port must be between 1 and 65535")
    paths.config.parent.mkdir(parents=True, exist_ok=True)
    username, password_hash = _webui_basic_credentials()
    content = (
        "[BitTorrent]\n"
        "Session\\PortForwardingEnabled=false\n"
        "Session\\ShareLimitAction=Stop\n\n"
        "[Network]\n"
        "PortForwardingEnabled=false\n\n"
        "[GUI]\n"
        "StartUpWindowState=Minimized\n\n"
        "[Preferences]\n"
        "Advanced\\updateCheck=false\n"
        "General\\NoSplashScreen=true\n"
        "General\\SystrayEnabled=false\n"
        f"WebUI\\APIKey={api_key}\n"
        "WebUI\\Address=127.0.0.1\n"
        "WebUI\\AuthSubnetWhitelistEnabled=false\n"
        "WebUI\\ClickjackingProtection=true\n"
        "WebUI\\CSRFProtection=true\n"
        "WebUI\\Enabled=true\n"
        "WebUI\\HostHeaderValidation=true\n"
        "WebUI\\HTTPS\\Enabled=false\n"
        "WebUI\\LocalHostAuth=true\n"
        f"WebUI\\Password_PBKDF2={password_hash}\n"
        f"WebUI\\Port={port}\n"
        "WebUI\\ServerDomains=127.0.0.1;localhost\n"
        f"WebUI\\Username={username}\n"
        "WebUI\\UseUPnP=false\n"
    )
    temporary = paths.config.with_name(f".{paths.config.name}.{secrets.token_hex(8)}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
        os.replace(temporary, paths.config)
    finally:
        temporary.unlink(missing_ok=True)


class ExclusiveFileLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._file: Any = None

    def __enter__(self) -> ExclusiveFileLock:
        self.acquire()
        return self

    def __exit__(self, *_: object) -> None:
        self.release()

    def acquire(self) -> None:
        if self._file is not None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        try:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError) as exc:
            handle.close()
            raise QbittorrentBusy("torrent engine is busy in another Retrofetch") from exc
        self._file = handle

    def release(self) -> None:
        if self._file is None:
            return
        handle = self._file
        self._file = None
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


def _powershell_executable() -> Path:
    system_root = os.environ.get("SystemRoot")
    if not system_root:
        raise QbittorrentSecurityError("Windows system directory is unavailable")
    executable = (
        Path(system_root)
        / "System32"
        / "WindowsPowerShell"
        / "v1.0"
        / "powershell.exe"
    )
    if not executable.is_file():
        raise QbittorrentSecurityError("Windows PowerShell is unavailable")
    return executable


def _windows_executable_identity(path: Path) -> WindowsExecutableIdentity:
    script = (
        "$item=Get-Item -LiteralPath $env:RETROFETCH_QB_IDENTITY_PATH;"
        "$sig=Get-AuthenticodeSignature -LiteralPath $item.FullName;"
        "[pscustomobject]@{"
        "product_name=[string]$item.VersionInfo.ProductName;"
        "original_filename=[string]$item.VersionInfo.OriginalFilename;"
        "company_name=[string]$item.VersionInfo.CompanyName;"
        "product_version=[string]$item.VersionInfo.ProductVersion;"
        "signature_status=[string]$sig.Status"
        "}|ConvertTo-Json -Compress"
    )
    environment = os.environ.copy()
    environment["RETROFETCH_QB_IDENTITY_PATH"] = str(path)
    try:
        completed = subprocess.run(
            [
                str(_powershell_executable()),
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                script,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            env=environment,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise QbittorrentSecurityError(
            "could not verify qBittorrent executable identity"
        ) from exc
    if completed.returncode != 0:
        raise QbittorrentSecurityError("could not verify qBittorrent executable identity")
    try:
        payload = json.loads(completed.stdout)
        values = tuple(
            payload[key]
            for key in (
                "product_name",
                "original_filename",
                "company_name",
                "product_version",
                "signature_status",
            )
        )
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise QbittorrentSecurityError(
            "could not verify qBittorrent executable identity"
        ) from exc
    if not all(isinstance(value, str) for value in values):
        raise QbittorrentSecurityError("could not verify qBittorrent executable identity")
    return WindowsExecutableIdentity(*values)


def _validate_windows_executable_identity(identity: WindowsExecutableIdentity) -> None:
    version = identity.product_version.strip().removeprefix("v")
    if (
        identity.product_name.strip().casefold() != "qbittorrent"
        or identity.original_filename.strip().casefold() != "qbittorrent.exe"
        or identity.company_name.strip().casefold() != QBITTORRENT_PUBLISHER.casefold()
        or version != QBITTORRENT_VERSION
        or identity.signature_status.strip().casefold() not in {"valid", "notsigned"}
    ):
        raise QbittorrentSecurityError(
            f"qBittorrent executable must be the pinned {QBITTORRENT_VERSION} release"
        )


def _verified_executable(path: Path, *, platform_name: str | None = None) -> Path:
    if not path.is_absolute():
        raise QbittorrentSecurityError("qBittorrent executable path must be absolute")
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise QbittorrentSecurityError("qBittorrent executable does not exist") from exc
    if not resolved.is_file():
        raise QbittorrentSecurityError("qBittorrent executable does not exist")
    platform_name = sys.platform if platform_name is None else platform_name
    name = resolved.name.casefold()
    if platform_name.startswith("win"):
        if name != "qbittorrent.exe":
            raise QbittorrentSecurityError("expected an installed qbittorrent.exe")
        _validate_windows_executable_identity(_windows_executable_identity(resolved))
    elif name not in {"qbittorrent", "qbittorrent-nox"} and not (
        name.startswith("qbittorrent-") and name.endswith(".appimage")
    ):
        raise QbittorrentSecurityError("expected an installed qBittorrent executable")
    elif not os.access(resolved, os.X_OK):
        raise QbittorrentSecurityError("qBittorrent executable is not runnable")
    return resolved


def _validate_managed_paths(paths: ManagedPaths) -> None:
    if not all(path.is_absolute() for path in (paths.root, paths.profile, paths.config, paths.lock)):
        raise QbittorrentSecurityError("managed qBittorrent paths must be absolute")
    root = paths.root.resolve(strict=False)
    if any(
        not path.resolve(strict=False).is_relative_to(root)
        for path in (paths.profile, paths.config, paths.lock)
    ):
        raise QbittorrentSecurityError("managed qBittorrent paths must remain app-private")


def discover_qbittorrent(
    explicit: str | Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    platform_name: str | None = None,
    home: str | Path | None = None,
) -> Path | None:
    """Discover an explicit executable or a known qBittorrent install location."""

    platform_name = sys.platform if platform_name is None else platform_name
    if explicit is not None:
        return _verified_executable(
            Path(explicit).expanduser(), platform_name=platform_name
        )
    env = os.environ if environ is None else environ
    candidates: list[Path] = []
    if platform_name.startswith("win"):
        for key in ("ProgramW6432", "ProgramFiles", "ProgramFiles(x86)"):
            if root := env.get(key):
                candidates.append(Path(root) / "qBittorrent" / "qbittorrent.exe")
        if local := env.get("LOCALAPPDATA"):
            candidates.extend(
                [
                    Path(local) / "Programs" / "qBittorrent" / "qbittorrent.exe",
                    Path(local) / "Microsoft" / "WinGet" / "Links" / "qbittorrent.exe",
                ]
            )
    elif platform_name == "darwin":
        home_path = Path(home).expanduser() if home is not None else Path.home()
        candidates.extend(
            [
                Path("/Applications/qBittorrent.app/Contents/MacOS/qbittorrent"),
                home_path
                / "Applications"
                / "qBittorrent.app"
                / "Contents"
                / "MacOS"
                / "qbittorrent",
                Path("/opt/homebrew/bin/qbittorrent"),
                Path("/usr/local/bin/qbittorrent"),
            ]
        )
    else:
        home_path = Path(home).expanduser() if home is not None else Path.home()
        candidates.extend(
            [
                Path("/usr/bin/qbittorrent-nox"),
                Path("/usr/bin/qbittorrent"),
                Path("/usr/local/bin/qbittorrent-nox"),
                Path("/usr/local/bin/qbittorrent"),
                home_path / ".local" / "bin" / "qbittorrent-nox",
                home_path / ".local" / "bin" / "qbittorrent",
            ]
        )
    for candidate in candidates:
        try:
            return _verified_executable(candidate, platform_name=platform_name)
        except QbittorrentSecurityError:
            continue
    return None


def _winget_version(version: str) -> str:
    if not re.fullmatch(r"5\.2\.\d+", version):
        raise ValueError("managed qBittorrent installs must pin a 5.2.x version")
    return version


def winget_show_command(
    version: str = QBITTORRENT_VERSION, *, executable: str | Path = "winget"
) -> tuple[str, ...]:
    return (
        str(executable),
        "show",
        "--id",
        QBITTORRENT_PACKAGE_ID,
        "--exact",
        "--version",
        _winget_version(version),
        "--source",
        "winget",
        "--accept-source-agreements",
        "--disable-interactivity",
    )


def winget_install_command(
    version: str = QBITTORRENT_VERSION, *, executable: str | Path = "winget"
) -> tuple[str, ...]:
    return (
        str(executable),
        "install",
        "--id",
        QBITTORRENT_PACKAGE_ID,
        "--exact",
        "--version",
        _winget_version(version),
        "--source",
        "winget",
        "--silent",
        "--disable-interactivity",
        "--accept-package-agreements",
        "--accept-source-agreements",
    )


def managed_command(
    executable: Path,
    paths: ManagedPaths,
    *,
    port: int,
    legal_notice_accepted: bool,
) -> tuple[str, ...]:
    executable = _verified_executable(executable)
    _validate_managed_paths(paths)
    if not legal_notice_accepted:
        raise QbittorrentSecurityError("qBittorrent legal notice was not accepted")
    if not 1 <= port <= 65535:
        raise ValueError("qBittorrent Web API port must be between 1 and 65535")
    return (
        str(executable),
        f"--profile={paths.profile}",
        "--configuration=retrofetch",
        f"--webui-port={port}",
        "--confirm-legal-notice",
        "--no-splash",
    )


@dataclass
class ManagedProcess:
    process: subprocess.Popen[bytes]
    client: QbittorrentClient
    lock: ExclusiveFileLock
    _closed: bool = False

    def shutdown(self, *, timeout: float = 10.0) -> None:
        if self._closed:
            return
        try:
            if self.process.poll() is None:
                try:
                    self.client.shutdown()
                except QbittorrentError:
                    pass
                try:
                    self.process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    self.process.terminate()
                    try:
                        self.process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        self.process.kill()
                        self.process.wait(timeout=5)
        finally:
            self.client.close()
            self.lock.release()
            self._closed = True


def start_managed(
    executable: Path,
    paths: ManagedPaths,
    *,
    api_key: str,
    port: int,
    legal_notice_accepted: bool,
    timeout: float = 20.0,
    transport: httpx.BaseTransport | None = None,
    stop_event: threading.Event | None = None,
) -> ManagedProcess:
    command = managed_command(
        executable,
        paths,
        port=port,
        legal_notice_accepted=legal_notice_accepted,
    )
    lock = ExclusiveFileLock(paths.lock)
    lock.acquire()
    process: subprocess.Popen[bytes] | None = None
    client: QbittorrentClient | None = None
    try:
        prepare_managed_profile(paths, api_key=api_key, port=port)
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        client = QbittorrentClient(
            f"http://127.0.0.1:{port}", api_key, transport=transport
        )
        client.wait_ready(timeout=timeout, process=process, stop_event=stop_event)
        return ManagedProcess(process, client, lock)
    except Exception:
        if client is not None:
            client.close()
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        lock.release()
        raise
