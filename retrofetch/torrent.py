from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import socket
import stat
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

import httpx

from retrofetch.config import Config
from retrofetch.downloader import finalize_staged_candidate, validate_candidate_file
from retrofetch.events import EventBus, GameBytesEvent, GameStageEvent
from retrofetch.qbittorrent import (
    QBITTORRENT_INSTALLER_SHA256,
    QBITTORRENT_INSTALLER_URL,
    QBITTORRENT_LINUX_APPIMAGES,
    QBITTORRENT_PACKAGE_ID,
    QBITTORRENT_PUBLISHER,
    QBITTORRENT_VERSION,
    ManagedProcess,
    ExclusiveFileLock,
    QbittorrentClient,
    QbittorrentError,
    QbittorrentProtocolError,
    QbittorrentUnavailable,
    discover_qbittorrent,
    generate_api_key,
    managed_paths,
    start_managed,
    winget_install_command,
    winget_show_command,
)
from retrofetch.sources import DownloadCancelled, DownloadCandidate, SourceUnavailable
from retrofetch.sanitize import sanitize_filename
from retrofetch.state import State, save_state, update_game

_INFOHASH_RE = re.compile(r"^[0-9a-f]{40}$")
_INSTALLER_MAX_BYTES = 128 * 1024 * 1024
_POLL_SECONDS = 0.5
_SETUP_MARKER = "consent-v1"
_RUNTIME_RECORD = "runtime.json"

SetupCallback = Callable[[], bool]


@dataclass(frozen=True)
class TorrentBatchItem:
    candidate: DownloadCandidate
    target_dir: Path
    game_title: str
    item_id: str


@dataclass(frozen=True)
class PreparedTorrent:
    staged_path: Path
    staging_root: Path


@dataclass(frozen=True)
class _ManagedRuntimeRecord:
    api_key: str
    port: int
    executable: Path
    pid: int | None = None
    launch_time: int | None = None


def _run_hidden(
    command: tuple[str, ...], *, timeout: float
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _validate_winget_show(output: str) -> None:
    required = (
        QBITTORRENT_PACKAGE_ID,
        f"Version: {QBITTORRENT_VERSION}",
        f"Publisher: {QBITTORRENT_PUBLISHER}",
        QBITTORRENT_INSTALLER_URL.rsplit("/download", 1)[0],
        QBITTORRENT_INSTALLER_SHA256,
    )
    folded = output.casefold()
    missing = [value for value in required if value.casefold() not in folded]
    if missing:
        raise SourceUnavailable(
            "WinGet qBittorrent package identity did not match the pinned release",
            retryable=False,
        )


def install_qbittorrent_winget() -> Path:
    """Validate then install the pinned WinGet package after TUI consent."""
    if os.name != "nt":
        raise SourceUnavailable("WinGet qBittorrent setup is only available on Windows")
    try:
        shown = _run_hidden(winget_show_command(), timeout=60)
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise SourceUnavailable(
            "WinGet is unavailable; use the verified installer option"
        ) from exc
    if shown.returncode != 0:
        raise SourceUnavailable(
            f"WinGet could not verify qBittorrent: {(shown.stderr or shown.stdout).strip()}",
            retryable=False,
        )
    _validate_winget_show(shown.stdout)
    executable = discover_qbittorrent()
    if executable is not None:
        return executable
    try:
        installed = _run_hidden(winget_install_command(), timeout=15 * 60)
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise SourceUnavailable("qBittorrent installation did not finish") from exc
    if installed.returncode != 0:
        raise SourceUnavailable(
            f"WinGet qBittorrent install failed: {(installed.stderr or installed.stdout).strip()}",
            retryable=False,
        )
    executable = discover_qbittorrent()
    if executable is None:
        raise SourceUnavailable(
            "qBittorrent installed but its executable was not found"
        )
    return executable


def install_qbittorrent_official() -> Path:
    """Download the pinned official installer, verify it, and open its visible UI."""
    if os.name != "nt":
        raise SourceUnavailable("The automatic qBittorrent installer is only available on Windows")
    paths = managed_paths()
    cache = paths.root / "installer"
    cache.mkdir(parents=True, exist_ok=True)
    installer = cache / f"qbittorrent_{QBITTORRENT_VERSION}_x64_setup.exe"
    temporary = installer.with_suffix(".download")
    digest = hashlib.sha256()
    try:
        with httpx.Client(timeout=60, follow_redirects=True, trust_env=False) as client:
            with client.stream("GET", QBITTORRENT_INSTALLER_URL) as response:
                response.raise_for_status()
                total = 0
                with temporary.open("wb") as handle:
                    for chunk in response.iter_bytes():
                        total += len(chunk)
                        if total > _INSTALLER_MAX_BYTES:
                            raise SourceUnavailable(
                                "qBittorrent installer exceeded the expected size",
                                retryable=False,
                            )
                        digest.update(chunk)
                        handle.write(chunk)
    except SourceUnavailable:
        temporary.unlink(missing_ok=True)
        raise
    except (OSError, httpx.HTTPError) as exc:
        temporary.unlink(missing_ok=True)
        raise SourceUnavailable(
            f"official qBittorrent installer download failed: {exc}"
        ) from exc
    if digest.hexdigest() != QBITTORRENT_INSTALLER_SHA256:
        temporary.unlink(missing_ok=True)
        raise SourceUnavailable(
            "qBittorrent installer SHA-256 mismatch", retryable=False
        )
    os.replace(temporary, installer)
    try:
        completed = subprocess.run([str(installer)], check=False)
    except OSError as exc:
        raise SourceUnavailable(f"could not open qBittorrent installer: {exc}") from exc
    if completed.returncode != 0:
        raise SourceUnavailable(
            "qBittorrent installer was cancelled or failed", retryable=False
        )
    executable = discover_qbittorrent()
    if executable is None:
        raise SourceUnavailable(
            "qBittorrent installer finished but the program was not found"
        )
    return executable


def install_qbittorrent_appimage(downloads_dir: str | Path | None = None) -> Path:
    """Verify a downloaded official AppImage and copy it into Retrofetch app data."""
    if not sys.platform.startswith("linux"):
        raise SourceUnavailable("AppImage qBittorrent setup is only available on Linux")
    downloads = (
        Path(downloads_dir).expanduser()
        if downloads_dir is not None
        else Path.home() / "Downloads"
    )
    for name, expected_digest in QBITTORRENT_LINUX_APPIMAGES.items():
        source = downloads / name
        if not source.is_file():
            continue
        if source.stat().st_size > _INSTALLER_MAX_BYTES:
            raise SourceUnavailable("qBittorrent AppImage exceeded the expected size")
        digest = hashlib.sha256()
        with source.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != expected_digest:
            raise SourceUnavailable(
                "qBittorrent AppImage checksum did not match the official release",
                retryable=False,
            )
        target_dir = managed_paths().root / "bin"
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / name
        temporary = target.with_suffix(".download")
        try:
            shutil.copyfile(source, temporary)
            temporary.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
        executable = discover_qbittorrent(target)
        if executable is None:
            raise SourceUnavailable("qBittorrent AppImage could not be prepared")
        return executable
    raise SourceUnavailable(
        f"Download qBittorrent {QBITTORRENT_VERSION} from the official page, then retry"
    )


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _write_runtime_record(
    path: Path,
    *,
    api_key: str,
    port: int,
    executable: Path,
    pid: int | None = None,
    launch_time: int | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(
            {
                "api_key": api_key,
                "port": port,
                "executable": str(executable),
                "pid": pid,
                "launch_time": launch_time,
            },
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def _read_runtime_record(path: Path) -> _ManagedRuntimeRecord | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        api_key = payload["api_key"]
        port = payload["port"]
        executable = Path(payload["executable"])
        pid = payload.get("pid")
        launch_time = payload.get("launch_time")
    except (OSError, KeyError, TypeError, ValueError):
        return None
    if (
        not isinstance(api_key, str)
        or not isinstance(port, int)
        or isinstance(port, bool)
        or not 1 <= port <= 65535
        or not executable.is_absolute()
        or (
            pid is not None
            and (not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0)
        )
        or (
            launch_time is not None
            and (
                not isinstance(launch_time, int)
                or isinstance(launch_time, bool)
                or launch_time <= 0
            )
        )
        or ((pid is None) != (launch_time is None))
    ):
        return None
    return _ManagedRuntimeRecord(api_key, port, executable, pid, launch_time)


def _windows_process_identity(pid: int) -> tuple[Path, int]:
    system_root = os.environ.get("SystemRoot")
    if not system_root:
        raise SourceUnavailable(
            "Windows process identity is unavailable", retryable=False
        )
    powershell = (
        Path(system_root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    )
    if not powershell.is_file():
        raise SourceUnavailable("Windows PowerShell is unavailable", retryable=False)
    environment = os.environ.copy()
    environment["RETROFETCH_QB_PID"] = str(pid)
    script = (
        "$p=Get-Process -Id ([int]$env:RETROFETCH_QB_PID) -ErrorAction Stop;"
        "[pscustomobject]@{path=[string]$p.Path;"
        "launch_time=([DateTimeOffset]$p.StartTime.ToUniversalTime())"
        ".ToUnixTimeSeconds()}|ConvertTo-Json -Compress"
    )
    try:
        completed = subprocess.run(
            [
                str(powershell),
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                script,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            env=environment,
        )
        payload = json.loads(completed.stdout) if completed.returncode == 0 else {}
        executable = Path(payload["path"])
        launch_time = payload["launch_time"]
    except (OSError, subprocess.TimeoutExpired, KeyError, TypeError, ValueError) as exc:
        raise SourceUnavailable(
            "could not verify the managed qBittorrent process", retryable=False
        ) from exc
    if (
        not executable.is_absolute()
        or not isinstance(launch_time, int)
        or isinstance(launch_time, bool)
        or launch_time <= 0
    ):
        raise SourceUnavailable(
            "could not verify the managed qBittorrent process", retryable=False
        )
    return executable.resolve(strict=True), launch_time


def _item_update(
    state: State,
    state_lock: threading.Lock | None,
    title: str,
    item_id: str,
    roms_root: Path | None = None,
    **fields: object,
) -> None:
    fields["item_id"] = item_id
    if state_lock is None:
        update_game(state, title, **fields)
        if roms_root is not None:
            save_state(state, roms_root)
        return
    with state_lock:
        update_game(state, title, **fields)
        if roms_root is not None:
            save_state(state, roms_root)


def _job_tags(job: dict[str, Any]) -> set[str]:
    raw = job.get("tags", "")
    return {part.strip() for part in str(raw).split(",") if part.strip()}


class TorrentCoordinator:
    """One run-scoped owner for qBittorrent setup, transfer, cancellation, and shutdown."""

    def __init__(
        self,
        config: Config,
        stop_event: threading.Event | None,
        *,
        setup_callback: SetupCallback | None = None,
        api_key: str | None = None,
        client: QbittorrentClient | None = None,
    ) -> None:
        self.config = config
        self.stop_event = stop_event
        self.setup_callback = setup_callback
        self.api_key = api_key
        self._client = client
        self._managed: ManagedProcess | None = None
        self._reattached_lock: ExclusiveFileLock | None = None
        self._reattached_port: int | None = None
        self._runtime_record: Path | None = None
        self._runtime_lock = threading.Lock()
        self._hash_locks: dict[str, threading.Lock] = {}
        self._active: set[str] = set()
        self._closed = False
        self._setup_decision: bool | None = None

    def _raise_if_stopped(self) -> None:
        if self.stop_event is not None and self.stop_event.is_set():
            raise DownloadCancelled("torrent setup cancelled")

    @staticmethod
    def _preferences_are_managed_safe(preferences: dict[str, Any]) -> bool:
        return (
            str(preferences.get("web_ui_address", ""))
            in {"127.0.0.1", "::1", "localhost"}
            and not bool(preferences.get("web_ui_upnp"))
            and not bool(preferences.get("upnp"))
            and not bool(preferences.get("bypass_local_auth"))
        )

    def _reattach_managed(self, paths) -> QbittorrentClient | None:
        record_path = paths.root / _RUNTIME_RECORD
        record = _read_runtime_record(record_path)
        if record is None:
            record_path.unlink(missing_ok=True)
            return None
        lock = ExclusiveFileLock(paths.lock)
        try:
            lock.acquire()
        except QbittorrentError as exc:
            raise SourceUnavailable(str(exc), retryable=False) from exc
        try:
            if record.pid is None or record.launch_time is None:
                raise SourceUnavailable(
                    "managed qBittorrent runtime identity is incomplete",
                    retryable=False,
                )
            verified = discover_qbittorrent(record.executable)
            if verified is None or verified != record.executable.resolve(strict=True):
                raise SourceUnavailable(
                    "managed qBittorrent executable identity changed",
                    retryable=False,
                )
            profile = paths.config.read_text(encoding="utf-8")
            if f"WebUI\\APIKey={record.api_key}\n" not in profile:
                raise SourceUnavailable(
                    "managed qBittorrent profile identity changed",
                    retryable=False,
                )
        except (OSError, QbittorrentError, SourceUnavailable) as exc:
            lock.release()
            if isinstance(exc, SourceUnavailable):
                raise
            raise SourceUnavailable(
                f"could not verify managed qBittorrent identity: {exc}",
                retryable=False,
            ) from exc
        client = QbittorrentClient(f"http://127.0.0.1:{record.port}", record.api_key)
        last_error: QbittorrentError | None = None
        for _ in range(10):
            if self.stop_event is not None and self.stop_event.is_set():
                client.close()
                lock.release()
                raise DownloadCancelled("torrent setup cancelled")
            try:
                client.assert_ready()
                launch_time = client.process_launch_time()
                if launch_time != record.launch_time:
                    raise SourceUnavailable(
                        "managed qBittorrent launch identity changed",
                        retryable=False,
                    )
                if os.name == "nt":
                    process_path, process_launch = _windows_process_identity(record.pid)
                    if (
                        process_path != record.executable.resolve(strict=True)
                        or abs(process_launch - record.launch_time) > 1
                    ):
                        raise SourceUnavailable(
                            "managed qBittorrent process identity changed",
                            retryable=False,
                        )
                if not self._preferences_are_managed_safe(client.preferences()):
                    raise SourceUnavailable(
                        "owned qBittorrent profile is no longer loopback/auth safe",
                        retryable=False,
                    )
                self._reattached_lock = lock
                self._reattached_port = record.port
                self._runtime_record = record_path
                self._client = client
                return client
            except QbittorrentUnavailable as exc:
                last_error = exc
                time.sleep(0.25)
            except SourceUnavailable:
                client.close()
                lock.release()
                raise
            except QbittorrentError as exc:
                client.close()
                lock.release()
                raise SourceUnavailable(
                    f"could not authenticate the existing managed qBittorrent: {exc}",
                    retryable=False,
                ) from exc
        client.close()
        lock.release()
        try:
            with socket.create_connection(("127.0.0.1", record.port), timeout=0.5):
                pass
        except OSError:
            record_path.unlink(missing_ok=True)
            return None
        raise SourceUnavailable(
            f"managed qBittorrent is running but unavailable: {last_error}",
            retryable=False,
        )

    def _ensure_client(self) -> QbittorrentClient:
        if self._client is not None:
            return self._client
        with self._runtime_lock:
            if self._client is not None:
                return self._client
            if self.config.torrent_mode == "disabled":
                raise SourceUnavailable("torrent support is disabled", retryable=False)
            if self.config.torrent_mode == "existing":
                key = self.api_key or os.environ.get("RETROFETCH_QBITTORRENT_API_KEY")
                if not key:
                    raise SourceUnavailable(
                        "existing qBittorrent mode needs RETROFETCH_QBITTORRENT_API_KEY",
                        retryable=False,
                    )
                client = QbittorrentClient(self.config.qbittorrent_url, key)
                client.assert_ready()
                preferences = client.preferences()
                if (
                    str(preferences.get("web_ui_address", ""))
                    not in {"127.0.0.1", "::1", "localhost"}
                    or bool(preferences.get("web_ui_upnp"))
                    or bool(preferences.get("upnp"))
                    or bool(preferences.get("bypass_local_auth"))
                ):
                    client.close()
                    raise SourceUnavailable(
                        "existing qBittorrent must require auth, bind WebUI to loopback, "
                        "and disable UPnP; use managed mode instead",
                        retryable=False,
                    )
                self._client = client
                return client

            paths = managed_paths()
            consent = paths.root / _SETUP_MARKER
            if consent.exists():
                reattached = self._reattach_managed(paths)
                if reattached is not None:
                    return reattached
            executable = discover_qbittorrent(self.config.qbittorrent_path)
            if executable is None or not consent.exists():
                self._raise_if_stopped()
                if self._setup_decision is False:
                    raise SourceUnavailable(
                        "qBittorrent setup was declined", retryable=False
                    )
                if self.setup_callback is None:
                    raise SourceUnavailable(
                        "qBittorrent setup is required; use the Retrofetch TUI once or --no-torrent",
                        retryable=False,
                    )
                self._setup_decision = self.setup_callback()
                self._raise_if_stopped()
                if not self._setup_decision:
                    raise SourceUnavailable(
                        "qBittorrent setup was declined", retryable=False
                    )
                executable = discover_qbittorrent(self.config.qbittorrent_path)
                if executable is None:
                    raise SourceUnavailable(
                        "qBittorrent setup completed but the program was not found"
                    )
                paths.root.mkdir(parents=True, exist_ok=True)
                consent.write_text(
                    "P2P and qBittorrent legal notice accepted\n", encoding="utf-8"
                )

            last_error: Exception | None = None
            runtime_record = paths.root / _RUNTIME_RECORD
            for _ in range(3):
                self._raise_if_stopped()
                api_key = generate_api_key()
                port = _free_loopback_port()
                _write_runtime_record(
                    runtime_record,
                    api_key=api_key,
                    port=port,
                    executable=executable,
                )
                managed: ManagedProcess | None = None
                try:
                    managed = start_managed(
                        executable,
                        paths,
                        api_key=api_key,
                        port=port,
                        legal_notice_accepted=True,
                        stop_event=self.stop_event,
                    )
                    launch_time = managed.client.process_launch_time()
                    _write_runtime_record(
                        runtime_record,
                        api_key=api_key,
                        port=port,
                        executable=executable,
                        pid=managed.process.pid,
                        launch_time=launch_time,
                    )
                    if not self._preferences_are_managed_safe(
                        managed.client.preferences()
                    ):
                        managed.shutdown(timeout=5)
                        raise SourceUnavailable(
                            "managed qBittorrent did not apply its safe local profile",
                            retryable=False,
                        )
                    self._managed = managed
                    self._runtime_record = runtime_record
                    self._client = managed.client
                    return managed.client
                except QbittorrentUnavailable as exc:
                    if managed is not None:
                        managed.shutdown(timeout=5)
                    last_error = exc
                    runtime_record.unlink(missing_ok=True)
                except Exception:
                    if managed is not None:
                        managed.shutdown(timeout=5)
                    runtime_record.unlink(missing_ok=True)
                    raise
            raise SourceUnavailable(
                f"managed qBittorrent failed to start: {last_error}"
            )

    def _lock_for(self, infohash: str) -> threading.Lock:
        with self._runtime_lock:
            return self._hash_locks.setdefault(infohash, threading.Lock())

    @staticmethod
    def _ownership_tag(
        state: State,
        state_lock: threading.Lock | None,
        item_ids: set[str],
        infohash: str,
    ) -> str:
        def stored_tags() -> set[str]:
            return {
                entry.tag
                for entry in state.games
                if entry.item_id in item_ids
                and entry.infohash == infohash
                and entry.tag
            }

        if state_lock is None:
            tags = stored_tags()
        else:
            with state_lock:
                tags = stored_tags()
        if len(tags) > 1:
            raise SourceUnavailable(
                "torrent items have conflicting ownership identities",
                retryable=False,
            )
        if tags:
            return next(iter(tags))
        return f"retrofetch-{infohash[:12]}-{secrets.token_hex(6)}"

    @staticmethod
    def _candidate_fields(
        candidate: DownloadCandidate,
    ) -> tuple[str, str, str, int, str]:
        extra = candidate.extra or {}
        url = extra.get("torrent_url")
        infohash = extra.get("torrent_infohash")
        path = extra.get("torrent_internal_path")
        index = extra.get("torrent_file_index")
        name = extra.get("torrent_name")
        if (
            not isinstance(url, str)
            or not isinstance(infohash, str)
            or not _INFOHASH_RE.fullmatch(infohash)
            or not isinstance(path, str)
            or not isinstance(index, int)
            or isinstance(index, bool)
            or index < 0
            or not isinstance(name, str)
        ):
            raise SourceUnavailable(
                "torrent candidate metadata is incomplete", retryable=False
            )
        return url, infohash, path, index, name

    @staticmethod
    def _qbittorrent_file_path(torrent_name: str, internal_path: str) -> str:
        """Translate a BEP-3 multi-file path to qBittorrent's rooted file name."""

        prefix = f"{torrent_name}/"
        return (
            internal_path
            if internal_path.startswith(prefix)
            else prefix + internal_path
        )

    @staticmethod
    def _emit_stage(
        event_bus: EventBus | None,
        game_title: str,
        item_id: str,
        stage: str,
        detail: str | None = None,
    ) -> None:
        if event_bus is not None:
            event_bus.publish(GameStageEvent(game_title, stage, detail, item_id))

    def _metadata(
        self,
        client: QbittorrentClient,
        url: str,
        game: str,
        item_id: str,
        bus: EventBus | None,
    ):
        self._emit_stage(bus, game, item_id, "Reading metadata")
        deadline = time.monotonic() + 30
        while True:
            metadata = client.fetch_metadata(url)
            if not metadata.pending:
                return metadata
            if time.monotonic() >= deadline:
                raise SourceUnavailable("qBittorrent metadata lookup timed out")
            if self.stop_event is not None:
                if self.stop_event.wait(_POLL_SECONDS):
                    raise DownloadCancelled("cancelled while reading torrent metadata")
            else:
                time.sleep(_POLL_SECONDS)

    @staticmethod
    def _owned_job(
        jobs: tuple[dict[str, Any], ...], infohash: str, tag: str, stage_root: Path
    ) -> dict[str, Any] | None:
        if not jobs:
            return None
        if len(jobs) != 1:
            raise SourceUnavailable(
                "qBittorrent returned duplicate jobs for one infohash", retryable=False
            )
        job = jobs[0]
        if str(job.get("hash", "")).casefold() != infohash:
            raise SourceUnavailable("qBittorrent job identity changed", retryable=False)
        if tag not in _job_tags(job):
            raise SourceUnavailable(
                "the same torrent already exists but is not owned by Retrofetch",
                retryable=False,
            )
        save_path = Path(str(job.get("save_path", ""))).resolve(strict=False)
        if save_path != stage_root.resolve(strict=False):
            raise SourceUnavailable(
                "qBittorrent job save path is outside Retrofetch staging",
                retryable=False,
            )
        return job

    @staticmethod
    def _selected_file(
        files: tuple[dict[str, Any], ...], index: int, path: str, size: int
    ):
        matches = [entry for entry in files if entry.get("index") == index]
        if len(matches) != 1:
            raise SourceUnavailable(
                "selected qBittorrent file index changed", retryable=False
            )
        selected = matches[0]
        if selected.get("name") != path or selected.get("size") != size:
            raise SourceUnavailable(
                "selected qBittorrent file metadata changed", retryable=False
            )
        return selected

    @staticmethod
    def _staged_file(
        job: dict[str, Any], stage_root: Path, torrent_name: str, internal_path: str
    ) -> Path:
        content = Path(str(job.get("content_path", "")))
        candidates = (
            content / Path(internal_path),
            stage_root / torrent_name / Path(internal_path),
            stage_root / Path(internal_path),
        )
        root = stage_root.resolve(strict=True)
        for candidate in candidates:
            try:
                resolved = candidate.resolve(strict=True)
            except OSError:
                continue
            if resolved.is_relative_to(root) and resolved.is_file():
                return resolved
        raise SourceUnavailable(
            "qBittorrent completed but the selected file was not found"
        )

    @staticmethod
    def _existing_selected_bytes(
        stage_root: Path,
        torrent_name: str,
        internal_path: str,
        expected_size: int,
    ) -> int:
        root = stage_root.resolve(strict=True)
        for candidate in (
            stage_root / torrent_name / Path(internal_path),
            stage_root / Path(internal_path),
        ):
            try:
                info = candidate.lstat()
                resolved = candidate.resolve(strict=True)
            except OSError:
                continue
            if (
                stat.S_ISLNK(info.st_mode)
                or (
                    getattr(info, "st_file_attributes", 0)
                    & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
                )
                or not resolved.is_relative_to(root)
                or not resolved.is_file()
            ):
                continue
            return min(expected_size, resolved.stat().st_size)
        return 0

    def transfer(
        self,
        candidate: DownloadCandidate,
        target_dir: Path,
        *,
        game_title: str,
        item_id: str,
        state: State,
        state_lock: threading.Lock | None,
        event_bus: EventBus | None,
    ) -> tuple[Path, Path]:
        item = TorrentBatchItem(candidate, Path(target_dir), game_title, item_id)
        result = self.transfer_many(
            [item], state=state, state_lock=state_lock, event_bus=event_bus
        )[item_id]
        if isinstance(result, SourceUnavailable):
            raise result
        return result.staged_path, result.staging_root

    def transfer_many(
        self,
        items: Sequence[TorrentBatchItem],
        *,
        state: State,
        state_lock: threading.Lock | None,
        event_bus: EventBus | None,
    ) -> dict[str, PreparedTorrent | SourceUnavailable]:
        if not items:
            return {}
        item_ids = [item.item_id for item in items]
        if len(set(item_ids)) != len(item_ids):
            raise ValueError("torrent batch item IDs must be unique")

        results: dict[str, PreparedTorrent | SourceUnavailable] = {}
        parsed: list[tuple[TorrentBatchItem, str, str, str, int, str]] = []
        for item in items:
            try:
                url, infohash, internal_path, file_index, torrent_name = (
                    self._candidate_fields(item.candidate)
                )
            except SourceUnavailable as exc:
                results[item.item_id] = exc
                continue
            parsed.append(
                (item, url, infohash, internal_path, file_index, torrent_name)
            )
        if not parsed:
            return results

        parsed.sort(key=lambda parsed_item: parsed_item[0].item_id)
        first_item, _first_url, infohash, _path, _index, _first_name = parsed[0]
        target_root = Path(first_item.target_dir).resolve()
        eligible: list[tuple[TorrentBatchItem, str, str, str, int, str]] = []
        for parsed_item in parsed:
            item, _item_url, item_hash, _path, _index, _item_name = parsed_item
            if item_hash != infohash or Path(item.target_dir).resolve() != target_root:
                results[item.item_id] = SourceUnavailable(
                    "torrent batch candidates do not share one exact collection",
                    retryable=False,
                )
                continue
            eligible.append(parsed_item)
        if not eligible:
            return results
        url = min(parsed_item[1] for parsed_item in eligible)

        active_ids = [item.item_id for item, *_fields in eligible]
        try:
            self._raise_if_stopped()
            lock = self._lock_for(infohash)
            with lock:
                self._raise_if_stopped()
                client = self._ensure_client()
                self._raise_if_stopped()
                for item, *_fields in eligible:
                    self._emit_stage(
                        event_bus, item.game_title, item.item_id, "Reading metadata"
                    )
                metadata = self._metadata(
                    client,
                    url,
                    first_item.game_title,
                    first_item.item_id,
                    None,
                )
                self._raise_if_stopped()
                if metadata.infohash_v1 != infohash:
                    raise SourceUnavailable(
                        "qBittorrent torrent infohash does not match MiNERVA",
                        retryable=False,
                    )
                if metadata.name is None:
                    raise SourceUnavailable(
                        "qBittorrent torrent metadata has no name",
                        retryable=False,
                    )
                torrent_name = metadata.name
                if sorted(entry.index for entry in metadata.files) != list(
                    range(len(metadata.files))
                ):
                    raise SourceUnavailable(
                        "qBittorrent returned non-contiguous file indexes",
                        retryable=False,
                    )

                selections: dict[str, tuple[TorrentBatchItem, str, str, int, int]] = {}
                for (
                    item,
                    _url,
                    _hash,
                    internal_path,
                    file_index,
                    candidate_name,
                ) in eligible:
                    if candidate_name != torrent_name:
                        results[item.item_id] = SourceUnavailable(
                            "qBittorrent torrent name does not match MiNERVA",
                            retryable=False,
                        )
                        continue
                    qbittorrent_path = self._qbittorrent_file_path(
                        torrent_name, internal_path
                    )
                    matches = [
                        entry
                        for entry in metadata.files
                        if entry.index == file_index and entry.path == qbittorrent_path
                    ]
                    casefold_matches = [
                        entry
                        for entry in metadata.files
                        if entry.path.casefold() == qbittorrent_path.casefold()
                    ]
                    if len(matches) != 1 or len(casefold_matches) != 1:
                        results[item.item_id] = SourceUnavailable(
                            "requested game is not the exact torrent file",
                            retryable=False,
                        )
                        continue
                    selected = matches[0]
                    if (
                        item.candidate.expected_size is not None
                        and selected.length != item.candidate.expected_size
                    ):
                        results[item.item_id] = SourceUnavailable(
                            "torrent file size changed since resolution",
                            retryable=False,
                        )
                        continue
                    if (
                        self.config.max_game_size_gb is not None
                        and selected.length
                        > int(self.config.max_game_size_gb * 1024**3)
                    ):
                        results[item.item_id] = SourceUnavailable(
                            "selected torrent file exceeds max_game_size_gb",
                            retryable=False,
                        )
                        continue
                    selections[item.item_id] = (
                        item,
                        internal_path,
                        qbittorrent_path,
                        file_index,
                        selected.length,
                    )

                ids_by_index: dict[int, list[str]] = {}
                for item_id, selection in selections.items():
                    ids_by_index.setdefault(selection[3], []).append(item_id)
                for duplicate_ids in ids_by_index.values():
                    if len(duplicate_ids) < 2:
                        continue
                    error = SourceUnavailable(
                        "multiple logical items select the same torrent file",
                        retryable=False,
                    )
                    for item_id in duplicate_ids:
                        results[item_id] = error
                        selections.pop(item_id, None)
                if not selections:
                    return results
                active_ids = list(selections)

                stage_root = (target_root / ".retrofetch-staging" / infohash).resolve()
                stage_root.mkdir(parents=True, exist_ok=True)
                required_bytes = sum(
                    length
                    - self._existing_selected_bytes(
                        stage_root,
                        torrent_name,
                        internal_path,
                        length,
                    )
                    for (
                        _item,
                        internal_path,
                        _qbt_path,
                        _file_index,
                        length,
                    ) in selections.values()
                )
                if (
                    shutil.disk_usage(stage_root).free
                    < required_bytes + 64 * 1024 * 1024
                ):
                    raise SourceUnavailable(
                        "insufficient free space for selected torrent files",
                        retryable=False,
                    )
                tag = self._ownership_tag(state, state_lock, set(selections), infohash)
                selected_indexes = {selection[3] for selection in selections.values()}
                priorities = [
                    1 if index in selected_indexes else 0
                    for index in range(len(metadata.files))
                ]
                for (
                    item,
                    internal_path,
                    _qbt_path,
                    file_index,
                    length,
                ) in selections.values():
                    _item_update(
                        state,
                        state_lock,
                        item.game_title,
                        item.item_id,
                        roms_root=self.config.roms_root,
                        status="pending",
                        provider=item.candidate.source,
                        infohash=infohash,
                        tag=tag,
                        selected_file_ids=[file_index],
                        selected_paths=[internal_path],
                        staging_path=str(stage_root),
                        final_path=str(Path(item.target_dir) / item.candidate.filename),
                        selected_bytes=length,
                        completed_bytes=0,
                        phase="planned",
                        outcome=None,
                        verification=None,
                    )

                job = self._owned_job(client.info(infohash), infohash, tag, stage_root)
                if job is None:
                    self._raise_if_stopped()
                    added = client.add(
                        url,
                        file_priorities=priorities,
                        save_path=stage_root,
                        tag=tag,
                        stopped=True,
                    )
                    if added.failure_count or infohash not in added.torrent_ids:
                        raise SourceUnavailable(
                            "qBittorrent refused the exact torrent job"
                        )
                    deadline = time.monotonic() + 10
                    while job is None and time.monotonic() < deadline:
                        job = self._owned_job(
                            client.info(infohash), infohash, tag, stage_root
                        )
                        if job is None:
                            time.sleep(0.1)
                    if job is None:
                        raise SourceUnavailable(
                            "qBittorrent did not attach the added torrent"
                        )

                client.stop(infohash)
                self._wait_stopped(client, infohash, timeout=2)
                all_indexes = list(range(len(priorities)))
                for start in range(0, len(all_indexes), 500):
                    client.set_file_priority(
                        infohash, all_indexes[start : start + 500], 0
                    )
                client.set_file_priority(infohash, sorted(selected_indexes), 1)
                files = client.files(infohash)
                for (
                    _item,
                    _path,
                    qbittorrent_path,
                    file_index,
                    length,
                ) in selections.values():
                    self._selected_file(files, file_index, qbittorrent_path, length)
                for entry in files:
                    index = entry.get("index")
                    expected_priority = 1 if index in selected_indexes else 0
                    if entry.get("priority") != expected_priority:
                        raise SourceUnavailable(
                            "qBittorrent did not apply the exact file priority vector",
                            retryable=False,
                        )
                for item, *_fields in selections.values():
                    _item_update(
                        state,
                        state_lock,
                        item.game_title,
                        item.item_id,
                        roms_root=self.config.roms_root,
                        phase="attached",
                    )
                    self._emit_stage(
                        event_bus,
                        item.game_title,
                        item.item_id,
                        "Starting torrent",
                    )

                self._active.add(infohash)
                safe_to_release = False
                stage_reported = False
                stopped_polls = 0
                try:
                    client.set_share_limits(infohash)
                    limited_job = self._owned_job(
                        client.info(infohash), infohash, tag, stage_root
                    )
                    if limited_job is None or not all(
                        isinstance(limited_job.get(key), (int, float))
                        and not isinstance(limited_job.get(key), bool)
                        and float(limited_job[key]) == 0
                        for key in (
                            "ratio_limit",
                            "seeding_time_limit",
                            "inactive_seeding_time_limit",
                        )
                    ):
                        raise SourceUnavailable(
                            "qBittorrent did not apply zero share limits",
                            retryable=False,
                        )
                    if (
                        str(limited_job.get("share_limit_action", "")).casefold()
                        != "stop"
                    ):
                        raise SourceUnavailable(
                            "qBittorrent did not apply the stop share-limit action",
                            retryable=False,
                        )
                    if self.stop_event is not None and self.stop_event.is_set():
                        client.stop(infohash)
                        self._wait_stopped(client, infohash, timeout=2)
                        safe_to_release = True
                        raise DownloadCancelled("torrent stopped before starting")
                    client.start(infohash)
                    for item, *_fields in selections.values():
                        _item_update(
                            state,
                            state_lock,
                            item.game_title,
                            item.item_id,
                            roms_root=self.config.roms_root,
                            phase="downloading",
                        )
                    while True:
                        if self.stop_event is not None and self.stop_event.is_set():
                            client.stop(infohash)
                            for item, *_fields in selections.values():
                                _item_update(
                                    state,
                                    state_lock,
                                    item.game_title,
                                    item.item_id,
                                    roms_root=self.config.roms_root,
                                    status="cancelled",
                                    phase="terminal",
                                    outcome="cancelled",
                                    verification="not_applicable",
                                )
                            try:
                                self._wait_stopped(client, infohash, timeout=2)
                                safe_to_release = True
                            except SourceUnavailable:
                                raise DownloadCancelled(
                                    "torrent stop requested; shutdown will retry"
                                ) from None
                            raise DownloadCancelled("torrent stopped; rerun to resume")
                        job = self._owned_job(
                            client.info(infohash), infohash, tag, stage_root
                        )
                        if job is None:
                            raise SourceUnavailable(
                                "qBittorrent torrent job disappeared"
                            )
                        current_files = client.files(infohash)
                        speed_bps = max(0, int(job.get("dlspeed", 0) or 0))
                        eta_seconds = max(0, int(job.get("eta", 0) or 0))
                        if eta_seconds >= 8_640_000:
                            eta_seconds = 0
                        seeds = max(0, int(job.get("num_seeds", 0) or 0))
                        peers = seeds + max(0, int(job.get("num_leechs", 0) or 0))
                        complete = True
                        for (
                            item,
                            _path,
                            qbittorrent_path,
                            file_index,
                            length,
                        ) in selections.values():
                            current = self._selected_file(
                                current_files,
                                file_index,
                                qbittorrent_path,
                                length,
                            )
                            progress = current.get("progress", 0.0)
                            if not isinstance(progress, (int, float)):
                                raise QbittorrentProtocolError(
                                    "qBittorrent returned invalid file progress"
                                )
                            downloaded = min(
                                length,
                                max(0, int(length * float(progress))),
                            )
                            complete = complete and downloaded >= length
                            _item_update(
                                state,
                                state_lock,
                                item.game_title,
                                item.item_id,
                                roms_root=self.config.roms_root,
                                completed_bytes=downloaded,
                            )
                            if event_bus is not None:
                                event_bus.publish(
                                    GameBytesEvent(
                                        item.game_title,
                                        downloaded,
                                        length,
                                        item.item_id,
                                        speed_bps=(
                                            speed_bps if len(selections) == 1 else None
                                        ),
                                        eta_seconds=eta_seconds or None,
                                        seeds=seeds,
                                        peers=peers,
                                    )
                                )
                        if complete:
                            break
                        state_folded = str(job.get("state", "")).casefold()
                        if state_folded in {"error", "missingfiles", "unknown"}:
                            raise SourceUnavailable(
                                "qBittorrent reported a torrent error"
                            )
                        if state_folded.startswith("stopped"):
                            stopped_polls += 1
                            if stopped_polls >= 5:
                                raise SourceUnavailable(
                                    "qBittorrent stopped before the selected files completed"
                                )
                        else:
                            stopped_polls = 0
                        if not stage_reported:
                            waiting = int(job.get("dlspeed", 0) or 0) == 0
                            for item, *_fields in selections.values():
                                self._emit_stage(
                                    event_bus,
                                    item.game_title,
                                    item.item_id,
                                    "Waiting for peers" if waiting else "Downloading",
                                    (
                                        f"seeds: {int(job.get('num_seeds', 0) or 0)}"
                                        if waiting
                                        else None
                                    ),
                                )
                            stage_reported = True
                        time.sleep(_POLL_SECONDS)

                    for item, *_fields in selections.values():
                        self._emit_stage(
                            event_bus,
                            item.game_title,
                            item.item_id,
                            "Finalizing",
                        )
                    client.stop(infohash)
                    self._wait_stopped(client, infohash, timeout=5)
                    final_job = self._owned_job(
                        client.info(infohash), infohash, tag, stage_root
                    )
                    if final_job is None:
                        raise SourceUnavailable(
                            "qBittorrent job disappeared before finalization"
                        )
                    prepared: dict[str, PreparedTorrent] = {}
                    staged_paths: set[Path] = set()
                    for item_id, (
                        _item,
                        internal_path,
                        _qbt_path,
                        _file_index,
                        _length,
                    ) in selections.items():
                        staged = self._staged_file(
                            final_job,
                            stage_root,
                            torrent_name,
                            internal_path,
                        )
                        resolved = staged.resolve(strict=True)
                        if resolved in staged_paths:
                            raise SourceUnavailable(
                                "torrent batch resolved multiple items to one file",
                                retryable=False,
                            )
                        staged_paths.add(resolved)
                        prepared[item_id] = PreparedTorrent(staged, stage_root)
                    client.delete(infohash)
                    deadline = time.monotonic() + 5
                    while client.info(infohash) and time.monotonic() < deadline:
                        time.sleep(0.1)
                    if client.info(infohash):
                        raise SourceUnavailable(
                            "qBittorrent job did not detach cleanly"
                        )
                    for item, *_fields in selections.values():
                        _item_update(
                            state,
                            state_lock,
                            item.game_title,
                            item.item_id,
                            roms_root=self.config.roms_root,
                            phase="finalizing",
                        )
                    safe_to_release = True
                except DownloadCancelled:
                    raise
                except Exception as exc:
                    try:
                        client.stop(infohash)
                        self._wait_stopped(client, infohash, timeout=2)
                        safe_to_release = True
                    except (QbittorrentError, SourceUnavailable):
                        pass
                    if isinstance(exc, QbittorrentError):
                        raise SourceUnavailable(
                            f"qBittorrent transfer failed: {exc}"
                        ) from exc
                    raise
                finally:
                    if safe_to_release:
                        self._active.discard(infohash)
        except QbittorrentError as exc:
            error: SourceUnavailable = SourceUnavailable(
                f"qBittorrent transfer failed: {exc}"
            )
            for item_id in active_ids:
                results.setdefault(item_id, error)
        except SourceUnavailable as exc:
            for item_id in active_ids:
                results.setdefault(item_id, exc)
        else:
            results.update(prepared)
        return results

    @staticmethod
    def _wait_stopped(
        client: QbittorrentClient, infohash: str, *, timeout: float
    ) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            jobs = client.info(infohash)
            if not jobs or str(jobs[0].get("state", "")).casefold().startswith(
                "stopped"
            ):
                return
            time.sleep(0.1)
        raise SourceUnavailable("qBittorrent did not acknowledge stop in time")

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        client = self._client
        if client is not None:
            for infohash in tuple(self._active):
                try:
                    client.stop(infohash)
                except QbittorrentError:
                    pass
        if self._managed is not None:
            try:
                self._managed.shutdown(timeout=5)
            finally:
                if self._runtime_record is not None:
                    self._runtime_record.unlink(missing_ok=True)
        elif self._reattached_lock is not None and client is not None:
            try:
                try:
                    client.shutdown()
                except QbittorrentError:
                    pass
                if self._reattached_port is not None:
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline:
                        try:
                            with socket.create_connection(
                                ("127.0.0.1", self._reattached_port), timeout=0.2
                            ):
                                time.sleep(0.1)
                        except OSError:
                            break
                client.close()
            finally:
                self._reattached_lock.release()
                if self._runtime_record is not None:
                    self._runtime_record.unlink(missing_ok=True)
        elif client is not None:
            client.close()


class TorrentTransferSource:
    """Downloader-compatible adapter around the shared torrent coordinator."""

    def __init__(
        self,
        coordinator: TorrentCoordinator,
        *,
        source_name: str,
        game_title: str,
        item_id: str,
        state: State,
        state_lock: threading.Lock | None,
        prepared: PreparedTorrent | None = None,
        transfer_error: Exception | None = None,
    ) -> None:
        if prepared is not None and transfer_error is not None:
            raise ValueError(
                "prepared torrent and transfer error are mutually exclusive"
            )
        self.name = source_name
        self.coordinator = coordinator
        self.game_title = game_title
        self.item_id = item_id
        self.state = state
        self.state_lock = state_lock
        self.prepared = prepared
        self.transfer_error = transfer_error

    def find_url_for_game(self, title: str, region_priority=None):
        return None

    def download(
        self,
        candidate: DownloadCandidate,
        dest_dir: Path,
        *,
        event_bus: EventBus | None = None,
    ) -> Path:
        target_root = Path(dest_dir).resolve()
        expected_final = target_root / sanitize_filename(
            candidate.filename, str(target_root)
        )
        if self.state_lock is None:
            entry = next(
                (game for game in self.state.games if game.item_id == self.item_id),
                None,
            )
        else:
            with self.state_lock:
                entry = next(
                    (game for game in self.state.games if game.item_id == self.item_id),
                    None,
                )
        extra = candidate.extra or {}
        if (
            entry is not None
            and entry.phase == "finalizing"
            and entry.infohash == extra.get("torrent_infohash")
            and entry.selected_paths == [extra.get("torrent_internal_path")]
            and entry.final_path is not None
            and Path(entry.final_path).resolve(strict=False)
            == expected_final.resolve(strict=False)
            and expected_final.exists()
        ):
            recovered = validate_candidate_file(expected_final, candidate)
            _item_update(
                self.state,
                self.state_lock,
                self.game_title,
                self.item_id,
                roms_root=self.coordinator.config.roms_root,
                completed_bytes=recovered.size,
                final_path=str(recovered.path),
                phase="finalizing",
            )
            return recovered.path
        if self.transfer_error is not None:
            raise self.transfer_error
        if self.prepared is None:
            staged, staging_root = self.coordinator.transfer(
                candidate,
                dest_dir,
                game_title=self.game_title,
                item_id=self.item_id,
                state=self.state,
                state_lock=self.state_lock,
                event_bus=event_bus,
            )
        else:
            staged = self.prepared.staged_path
            staging_root = self.prepared.staging_root
        finalized = finalize_staged_candidate(
            staged,
            staging_root=staging_root,
            target_dir=dest_dir,
            candidate=candidate,
        )
        _item_update(
            self.state,
            self.state_lock,
            self.game_title,
            self.item_id,
            roms_root=self.coordinator.config.roms_root,
            completed_bytes=finalized.size,
            final_path=str(finalized.path),
            phase="finalizing",
        )
        return finalized.path
