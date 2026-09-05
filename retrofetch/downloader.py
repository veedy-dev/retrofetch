from __future__ import annotations

import hashlib
import logging
import os
import stat
import threading
import time
import zipfile
import zlib
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit

import httpx

from retrofetch.dat import GameEntry, Rom, VerifyResult, verify_file
from retrofetch.events import (
    EventBus,
    GameBytesEvent,
    GameCancelledEvent,
    GameDoneEvent,
    GameSkippedEvent,
    GameUnverifiedEvent,
    ProgressEvent,
    RateLimitEvent,
)
from retrofetch.extractor import ExtractionError, extract_archive, is_archive
from retrofetch.sanitize import sanitize_filename
from retrofetch.sources import DownloadCancelled, DownloadCandidate, SourceUnavailable
from retrofetch.state import GameAttempt, State, update_game
from retrofetch.state import GameEntry as StateGameEntry

logger = logging.getLogger(__name__)

MAX_ATTEMPTS_PER_SOURCE = 3
USER_AGENT = "retrofetch/2.0 (+https://github.com/veedy-dev/retrofetch)"
_HOST_MIN_INTERVAL_S = 0.25
_HOST_LOCK = threading.Lock()
_HOST_LAST_REQUEST: dict[str, float] = {}
_HOST_FAILURES: dict[str, int] = {}
_HOST_CIRCUIT_UNTIL: dict[str, float] = {}


class Source(Protocol):
    name: str

    def find_url_for_game(
        self, title: str, region_priority: list[str] | None = None
    ) -> DownloadCandidate | None: ...

    def download(
        self,
        candidate: DownloadCandidate,
        dest_dir: Path,
        *,
        event_bus: EventBus | None = None,
    ) -> Path: ...


class DownloadResult:
    def __init__(
        self,
        status: str,
        filename: str | None = None,
        source: str | None = None,
        reason: str | None = None,
    ):
        self.status = status
        self.filename = filename
        self.source = source
        self.reason = reason

    def __repr__(self) -> str:
        return (
            f"DownloadResult(status={self.status!r}, filename={self.filename!r}, "
            f"source={self.source!r}, reason={self.reason!r})"
        )


@dataclass(frozen=True)
class StreamDownloadResult:
    path: Path
    resumed: bool
    bytes_written: int


@dataclass(frozen=True)
class FinalizeResult:
    path: Path
    size: int
    sha1: str | None = None
    crc32: str | None = None
    md5: str | None = None


def validate_candidate_file(path: Path, candidate: DownloadCandidate) -> FinalizeResult:
    """Validate one provider artifact without moving it."""
    source = Path(path)
    resolved = source.resolve(strict=True)
    info = source.lstat()
    if stat.S_ISLNK(info.st_mode) or (
        getattr(info, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    ):
        raise SourceUnavailable(
            "candidate file is a link or reparse point", retryable=False
        )
    if not resolved.is_file():
        raise SourceUnavailable(
            "candidate payload is not a regular file", retryable=False
        )

    size = resolved.stat().st_size
    if candidate.expected_size is not None and size != candidate.expected_size:
        raise SourceUnavailable(
            f"staged torrent size mismatch: expected {candidate.expected_size}, got {size}",
            retryable=False,
        )

    expected_md5 = None
    if candidate.extra is not None:
        raw_md5 = candidate.extra.get("artifact_md5")
        expected_md5 = str(raw_md5).lower() if raw_md5 else None
    need_sha1 = bool(candidate.expected_sha1)
    need_crc32 = bool(candidate.expected_crc32)
    need_md5 = bool(expected_md5)
    sha1 = hashlib.sha1() if need_sha1 else None
    md5 = hashlib.md5(usedforsecurity=False) if need_md5 else None
    crc32 = 0
    if need_sha1 or need_crc32 or need_md5:
        with resolved.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                if sha1 is not None:
                    sha1.update(chunk)
                if md5 is not None:
                    md5.update(chunk)
                if need_crc32:
                    crc32 = zlib.crc32(chunk, crc32)
    actual_sha1 = sha1.hexdigest() if sha1 is not None else None
    actual_md5 = md5.hexdigest() if md5 is not None else None
    actual_crc32 = f"{crc32 & 0xFFFFFFFF:08x}" if need_crc32 else None
    checks = (
        ("SHA1", candidate.expected_sha1, actual_sha1),
        ("CRC32", candidate.expected_crc32, actual_crc32),
        ("MD5", expected_md5, actual_md5),
    )
    for label, expected, actual in checks:
        if expected and actual != expected.lower():
            raise SourceUnavailable(f"staged torrent {label} mismatch", retryable=False)
    return FinalizeResult(
        path=resolved,
        size=size,
        sha1=actual_sha1,
        crc32=actual_crc32,
        md5=actual_md5,
    )


def finalize_staged_candidate(
    staged_path: Path,
    *,
    staging_root: Path,
    target_dir: Path,
    candidate: DownloadCandidate,
) -> FinalizeResult:
    """Validate one staged payload and atomically promote it without clobbering."""
    root = Path(staging_root).resolve(strict=True)
    staged = Path(staged_path)
    resolved = staged.resolve(strict=True)
    if not resolved.is_relative_to(root):
        raise SourceUnavailable(
            "staged torrent file escapes its private directory", retryable=False
        )
    validated = validate_candidate_file(staged, candidate)

    filename = Path(candidate.filename)
    if filename.name != candidate.filename:
        raise SourceUnavailable("torrent filename contains a path", retryable=False)
    destination_root = Path(target_dir)
    destination_root.mkdir(parents=True, exist_ok=True)
    destination = destination_root / sanitize_filename(
        candidate.filename, str(destination_root)
    )
    if destination.exists() and destination.resolve() != resolved:
        raise SourceUnavailable(
            f"refusing to overwrite existing file: {destination.name}", retryable=False
        )
    if destination.resolve(strict=False) != resolved:
        os.replace(resolved, destination)
    return FinalizeResult(
        path=destination,
        size=validated.size,
        sha1=validated.sha1,
        crc32=validated.crc32,
        md5=validated.md5,
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rom_for_verification(game: GameEntry, filename: str) -> Rom | None:
    for rom in game.roms:
        if rom.name == filename:
            return rom
    if game.roms:
        return game.roms[0]
    return None


def _record_attempt(
    state: State,
    game_title: str,
    source_name: str,
    result: str,
    item_id: str | None = None,
) -> None:
    attempt = GameAttempt(source=source_name, result=result, ts=_now())
    for g in state.games:
        if (item_id is not None and g.item_id == item_id) or (
            item_id is None and g.title == game_title
        ):
            g.attempts.append(attempt)
            return
    update_game(
        state,
        game_title,
        status="pending",
        attempts=[attempt],
        item_id=item_id,
    )


def _content_length(headers: httpx.Headers) -> int | None:
    raw = headers.get("Content-Length")
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _host_for_url(url: str) -> str:
    parts = urlsplit(url)
    return parts.netloc.casefold()


def _wait_for_host_slot(url: str, source_name: str) -> None:
    host = _host_for_url(url)
    if not host:
        return
    with _HOST_LOCK:
        until = _HOST_CIRCUIT_UNTIL.get(host, 0.0)
        now = time.monotonic()
        if now < until:
            raise SourceUnavailable(
                f"{source_name} host circuit open for {until - now:.1f}s"
            )
        last = _HOST_LAST_REQUEST.get(host, 0.0)
        wait_for = max(0.0, _HOST_MIN_INTERVAL_S - (now - last))
        if wait_for:
            time.sleep(wait_for)
        _HOST_LAST_REQUEST[host] = time.monotonic()


def _record_http_status(url: str, status_code: int) -> None:
    host = _host_for_url(url)
    if not host:
        return
    with _HOST_LOCK:
        if status_code in (403, 429):
            failures = _HOST_FAILURES.get(host, 0) + 1
            _HOST_FAILURES[host] = failures
            if failures >= 5:
                _HOST_CIRCUIT_UNTIL[host] = time.monotonic() + 60.0
            return
        if status_code < 400:
            _HOST_FAILURES[host] = 0
            _HOST_CIRCUIT_UNTIL.pop(host, None)


def stream_http_download(
    url: str,
    final_path: Path,
    *,
    event_bus: EventBus | None = None,
    event_game: str | None = None,
    timeout: float = 60.0,
    source_name: str = "http",
    expected_size: int | None = None,
) -> StreamDownloadResult:
    """Stream an HTTP URL through a .part file and atomically replace final."""

    final = Path(final_path)
    final.parent.mkdir(parents=True, exist_ok=True)
    part = final.with_suffix(final.suffix + ".part")
    resume_from = part.stat().st_size if part.exists() else 0
    supports_range = False
    remote_size: int | None = expected_size

    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            if resume_from:
                try:
                    _wait_for_host_slot(url, source_name)
                    head = client.head(url, headers={"User-Agent": USER_AGENT})
                    _record_http_status(url, head.status_code)
                    if head.status_code < 400:
                        accept_ranges = head.headers.get("Accept-Ranges", "")
                        supports_range = "bytes" in accept_ranges.lower()
                        remote_size = _content_length(head.headers) or remote_size
                except httpx.HTTPError:
                    supports_range = False

                if remote_size is not None and resume_from > remote_size:
                    part.unlink(missing_ok=True)
                    resume_from = 0

            headers: dict[str, str] = {"User-Agent": USER_AGENT}
            mode = "wb"
            downloaded = 0
            resumed = False
            range_requested = False
            if resume_from and supports_range:
                headers["Range"] = f"bytes={resume_from}-"
                mode = "ab"
                downloaded = resume_from
                resumed = True
                range_requested = True

            _wait_for_host_slot(url, source_name)
            with client.stream("GET", url, headers=headers) as resp:
                _record_http_status(url, resp.status_code)
                if resp.status_code == 429 and event_bus is not None:
                    retry_after = resp.headers.get("Retry-After")
                    try:
                        retry_after_s = float(retry_after) if retry_after else 60.0
                    except ValueError:
                        retry_after_s = 60.0
                    event_bus.publish(
                        RateLimitEvent(source=source_name, retry_after=retry_after_s)
                    )
                if resp.status_code == 416:
                    part.unlink(missing_ok=True)
                    resp.close()
                    return stream_http_download(
                        url,
                        final,
                        event_bus=event_bus,
                        event_game=event_game,
                        timeout=timeout,
                        source_name=source_name,
                        expected_size=expected_size,
                    )
                if resp.status_code == 200 and range_requested:
                    mode = "wb"
                    downloaded = 0
                    resumed = False
                elif resp.status_code == 206 and range_requested:
                    resumed = True
                elif resp.status_code != 200:
                    raise SourceUnavailable(
                        f"{source_name} HTTP {resp.status_code}",
                        retryable=resp.status_code in (408, 429)
                        or resp.status_code >= 500,
                    )

                content_type = resp.headers.get("Content-Type", "")
                if "text/html" in content_type.lower() and final.suffix.lower() not in (
                    ".html",
                    ".htm",
                ):
                    raise SourceUnavailable(
                        f"{source_name} returned HTML page instead of file content",
                        retryable=False,
                    )

                content_length = _content_length(resp.headers)
                if resp.status_code == 206:
                    total = remote_size or (
                        downloaded + content_length
                        if content_length is not None
                        else None
                    )
                else:
                    total = content_length or remote_size
                    if (
                        total is not None
                        and part.exists()
                        and part.stat().st_size > total
                    ):
                        part.unlink(missing_ok=True)

                with open(part, mode) as fh:
                    for chunk in resp.iter_bytes(chunk_size=64 * 1024):
                        if not chunk:
                            continue
                        fh.write(chunk)
                        downloaded += len(chunk)
                        if event_bus is not None:
                            event_bus.publish(
                                GameBytesEvent(
                                    game=event_game or final.name,
                                    downloaded=downloaded,
                                    total=total or 0,
                                )
                            )
    except SourceUnavailable:
        raise
    except httpx.HTTPError as exc:
        raise SourceUnavailable(f"{source_name} download error: {exc}") from exc
    except OSError as exc:
        raise SourceUnavailable(
            f"{source_name} file write error: {exc}", retryable=False
        ) from exc

    try:
        os.replace(part, final)
    except OSError as exc:
        raise SourceUnavailable(
            f"{source_name} atomic replace failed: {exc}", retryable=False
        ) from exc
    return StreamDownloadResult(path=final, resumed=resumed, bytes_written=downloaded)


def _recorded_file_matches(entry: StateGameEntry, target_dir: Path) -> bool:
    if not entry.filename:
        return False
    root = Path(target_dir).resolve(strict=False)
    candidate = Path(target_dir) / entry.filename
    try:
        info = candidate.lstat()
        resolved = candidate.resolve(strict=True)
    except OSError:
        return False
    if (
        stat.S_ISLNK(info.st_mode)
        or (
            getattr(info, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        )
        or not resolved.is_relative_to(root)
        or not resolved.is_file()
    ):
        return False
    if entry.size_bytes is not None and resolved.stat().st_size != entry.size_bytes:
        return False
    if not entry.sha1 and not entry.crc32:
        return True
    sha1 = hashlib.sha1() if entry.sha1 else None
    crc32 = 0
    with resolved.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            if sha1 is not None:
                sha1.update(chunk)
            if entry.crc32:
                crc32 = zlib.crc32(chunk, crc32)
    return (
        not entry.sha1 or sha1 is not None and sha1.hexdigest() == entry.sha1.lower()
    ) and (not entry.crc32 or f"{crc32 & 0xFFFFFFFF:08x}" == entry.crc32.lower())


def _acquired_filename(state: State, game_title: str, target_dir: Path) -> str | None:
    for entry in state.games:
        acquired = entry.outcome == "acquired" or entry.status in {
            "acquired",
            "unverified",
        }
        if (
            entry.title == game_title
            and acquired
            and entry.filename
            and _recorded_file_matches(entry, target_dir)
        ):
            return entry.filename
    return None


def skip_if_acquired(
    state: State,
    game_title: str,
    target_dir: Path,
    *,
    event_bus: EventBus | None = None,
    item_id: str | None = None,
) -> DownloadResult | None:
    filename = _acquired_filename(state, game_title, target_dir)
    if filename is None:
        return None
    if event_bus is not None:
        event_bus.publish(
            GameSkippedEvent(
                game=game_title,
                reason="already acquired",
                filename=filename,
                item_id=item_id,
            )
        )
    return DownloadResult(
        status="skipped",
        filename=filename,
        reason="already acquired",
    )


def _zip_members(archive: Path) -> list[zipfile.ZipInfo]:
    with zipfile.ZipFile(archive) as zf:
        return [info for info in zf.infolist() if not info.is_dir()]


def _verify_zip_member(archive: Path, expected: Rom) -> VerifyResult | None:
    try:
        with zipfile.ZipFile(archive) as zf:
            candidates = [info for info in zf.infolist() if not info.is_dir()]
            exact = [
                info for info in candidates if Path(info.filename).name == expected.name
            ]
            if exact:
                info = exact[0]
            elif len(candidates) == 1:
                info = candidates[0]
            else:
                return None
            if expected.size and info.file_size != expected.size:
                return VerifyResult(
                    False,
                    f"zip member size mismatch: expected {expected.size}, got {info.file_size}",
                    "",
                    "",
                    "",
                )
            sha1 = hashlib.sha1()
            md5 = hashlib.md5()
            crc = 0
            with zf.open(info) as fh:
                while True:
                    chunk = fh.read(1024 * 1024)
                    if not chunk:
                        break
                    sha1.update(chunk)
                    md5.update(chunk)
                    crc = zlib.crc32(chunk, crc)
            sha1_hex = sha1.hexdigest()
            md5_hex = md5.hexdigest()
            crc_hex = f"{crc & 0xFFFFFFFF:08x}"
            if expected.sha1 and sha1_hex.lower() != expected.sha1.lower():
                return VerifyResult(
                    False,
                    f"sha1 mismatch: expected {expected.sha1}, got {sha1_hex}",
                    sha1_hex,
                    crc_hex,
                    md5_hex,
                )
            if expected.crc32 and crc_hex.lower() != expected.crc32.lower():
                return VerifyResult(
                    False,
                    f"crc32 mismatch: expected {expected.crc32}, got {crc_hex}",
                    sha1_hex,
                    crc_hex,
                    md5_hex,
                )
            if expected.md5 and md5_hex.lower() != expected.md5.lower():
                return VerifyResult(
                    False,
                    f"md5 mismatch: expected {expected.md5}, got {md5_hex}",
                    sha1_hex,
                    crc_hex,
                    md5_hex,
                )
            return VerifyResult(True, None, sha1_hex, crc_hex, md5_hex)
    except (OSError, zipfile.BadZipFile):
        return None


def _verify_downloaded(
    downloaded: Path,
    rom: Rom,
    *,
    extract_archives: bool,
) -> tuple[str, str | None]:
    if not extract_archives and is_archive(downloaded):
        if downloaded.suffix.lower() == ".zip":
            result = _verify_zip_member(downloaded, rom)
            if result is None:
                return ("unverified", "zip member not found")
            if result.matched:
                return ("verified", None)
            return ("failed", result.reason or "hash mismatch")
        return (
            "unverified",
            f"archive verification unsupported for {downloaded.suffix}",
        )
    result = verify_file(downloaded, rom)
    if result.matched:
        return ("verified", None)
    return ("failed", result.reason or "hash mismatch")


def download_game(
    source: Source,
    candidate: DownloadCandidate,
    target_dir: Path,
    game: GameEntry | None,
    game_title: str,
    state: State,
    *,
    console: str,
    event_bus: EventBus | None = None,
    extract_archives: bool = False,
    verification_available: bool = True,
    state_lock: threading.Lock | None = None,
    item_id: str | None = None,
) -> DownloadResult:
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    def record_attempt(result: str) -> None:
        if state_lock is None:
            _record_attempt(state, game_title, source.name, result, item_id)
            return
        with state_lock:
            _record_attempt(state, game_title, source.name, result, item_id)

    def update_status(status: str, **kwargs: object) -> None:
        kwargs["item_id"] = item_id
        if state_lock is None:
            update_game(state, game_title, status=status, **kwargs)
            return
        with state_lock:
            update_game(state, game_title, status=status, **kwargs)

    if state_lock is None:
        skipped = skip_if_acquired(
            state,
            game_title,
            target_dir,
            event_bus=event_bus,
            item_id=item_id,
        )
    else:
        with state_lock:
            skipped = skip_if_acquired(
                state,
                game_title,
                target_dir,
                event_bus=event_bus,
                item_id=item_id,
            )
    if skipped is not None:
        return skipped

    source_bus = EventBus() if event_bus is not None else None
    subscription = None
    if source_bus is not None and event_bus is not None:

        def forward(event: ProgressEvent) -> None:
            event_bus.publish(
                replace(event, game=game_title, item_id=item_id)
                if isinstance(event, GameBytesEvent)
                else event
            )

        subscription = source_bus.subscribe(forward)

    try:
        last_reason: str | None = None
        for attempt_num in range(1, MAX_ATTEMPTS_PER_SOURCE + 1):
            try:
                downloaded = source.download(
                    candidate, target_dir, event_bus=source_bus
                )
            except DownloadCancelled as exc:
                reason = str(exc)
                record_attempt(f"cancelled: {reason}")
                update_status(
                    "cancelled",
                    source=source.name,
                    provider=source.name,
                    phase="terminal",
                    outcome="cancelled",
                    verification="not_applicable",
                )
                if event_bus is not None:
                    event_bus.publish(GameCancelledEvent(game_title, reason, item_id))
                return DownloadResult(
                    status="cancelled", source=source.name, reason=reason
                )
            except SourceUnavailable as exc:
                last_reason = str(exc)
                logger.warning(
                    "download attempt %s/%s failed for %s via %s: %s",
                    attempt_num,
                    MAX_ATTEMPTS_PER_SOURCE,
                    game_title,
                    source.name,
                    exc,
                )
                record_attempt(f"download_failed: {exc}")
                if not exc.retryable:
                    break
                if attempt_num < MAX_ATTEMPTS_PER_SOURCE:
                    time.sleep(min(2 ** (attempt_num - 1), 5))
                continue
            except Exception as exc:
                last_reason = f"unexpected: {exc}"
                # Keep credential-bearing exception text and chains out of logs.
                logger.exception(
                    "unexpected download error for %s: %s",
                    game_title,
                    type(exc).__name__,
                    exc_info=False,
                )
                record_attempt(last_reason)
                continue

            verified = True
            verify_reason: str | None = None
            verification_status = "verified"
            if not verification_available:
                verification_status = "unverified"
                verify_reason = "DAT not available; download is unverified"
            elif game is None:
                verification_status = "unverified"
                verify_reason = "DAT entry not found; download is unverified"
            else:
                rom = _rom_for_verification(game, downloaded.name)
                if rom is None or not (rom.sha1 or rom.crc32 or rom.md5):
                    verification_status = "unverified"
                    verify_reason = "DAT hash not available; download is unverified"
                else:
                    verification_status, verify_reason = _verify_downloaded(
                        downloaded,
                        rom,
                        extract_archives=extract_archives,
                    )
                    verified = verification_status != "failed"

            if not verified:
                last_reason = verify_reason or "hash mismatch"
                logger.warning(
                    "verify failed for %s attempt %s: %s",
                    game_title,
                    attempt_num,
                    last_reason,
                )
                record_attempt(f"verify_failed: {last_reason}")
                try:
                    downloaded.unlink()
                except OSError:
                    pass
                continue

            if verification_status == "unverified":
                final_filename = downloaded.name
                if extract_archives and is_archive(downloaded):
                    try:
                        extracted = extract_archive(downloaded, target_dir)
                    except ExtractionError as exc:
                        last_reason = f"extract_failed: {exc}"
                        record_attempt(last_reason)
                        continue
                    try:
                        downloaded.unlink()
                    except OSError:
                        pass
                    if len(extracted) == 1:
                        final_filename = extracted[0].name
                    else:
                        final_filename = ",".join(p.name for p in extracted)
                final_filename = sanitize_filename(final_filename)
                record_attempt(f"unverified: {verify_reason or 'not verified'}")
                update_status(
                    "unverified",
                    source=source.name,
                    provider=source.name,
                    filename=final_filename,
                    sha1=candidate.expected_sha1,
                    crc32=candidate.expected_crc32,
                    size_bytes=candidate.expected_size,
                    completed_bytes=candidate.expected_size or 0,
                    final_path=str(target_dir / final_filename),
                    phase="terminal",
                    outcome="acquired",
                    verification="unverified",
                )
                if event_bus is not None:
                    event_bus.publish(
                        GameUnverifiedEvent(
                            game=game_title,
                            source=source.name,
                            reason=verify_reason,
                            item_id=item_id,
                        )
                    )
                return DownloadResult(
                    status="unverified",
                    filename=final_filename,
                    source=source.name,
                    reason=verify_reason,
                )

            final_filename = downloaded.name
            if extract_archives and is_archive(downloaded):
                try:
                    extracted = extract_archive(downloaded, target_dir)
                except ExtractionError as exc:
                    last_reason = f"extract_failed: {exc}"
                    record_attempt(last_reason)
                    continue
                try:
                    downloaded.unlink()
                except OSError:
                    pass
                if len(extracted) == 1:
                    final_filename = extracted[0].name
                else:
                    final_filename = ",".join(p.name for p in extracted)

            sanitized = sanitize_filename(final_filename)
            record_attempt("success")
            update_status(
                "acquired",
                source=source.name,
                provider=source.name,
                filename=sanitized,
                sha1=candidate.expected_sha1,
                crc32=candidate.expected_crc32,
                size_bytes=candidate.expected_size,
                completed_bytes=candidate.expected_size or 0,
                final_path=str(target_dir / sanitized),
                phase="terminal",
                outcome="acquired",
                verification="verified",
            )
            if event_bus is not None:
                event_bus.publish(
                    GameDoneEvent(
                        game=game_title,
                        source=source.name,
                        size=candidate.expected_size or 0,
                        sha1=candidate.expected_sha1,
                        item_id=item_id,
                    )
                )
            return DownloadResult(
                status="acquired", filename=sanitized, source=source.name
            )

        update_status(
            "failed",
            source=source.name,
            provider=source.name,
            phase="terminal",
            outcome="failed",
            verification="not_applicable",
        )
        final_reason = last_reason or "exhausted attempts"
        return DownloadResult(
            status="failed",
            source=source.name,
            reason=final_reason,
        )
    finally:
        if source_bus is not None and subscription is not None:
            source_bus.unsubscribe(subscription)
