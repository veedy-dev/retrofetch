from __future__ import annotations

import logging
import os
import zipfile
import hashlib
import zlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

import httpx

from retrofetch.dat import GameEntry, Rom, VerifyResult, verify_file
from retrofetch.events import (
    EventBus,
    GameBytesEvent,
    GameDoneEvent,
    GameFailedEvent,
    GameSkippedEvent,
    GameStartEvent,
)
from retrofetch.extractor import ExtractionError, extract_archive, is_archive
from retrofetch.sanitize import sanitize_filename
from retrofetch.sources import DownloadCandidate, SourceUnavailable
from retrofetch.state import GameAttempt, State, update_game

_log = logging.getLogger(__name__)

MAX_ATTEMPTS_PER_SOURCE = 3


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
    state: State, game_title: str, source_name: str, result: str
) -> None:
    attempt = GameAttempt(source=source_name, result=result, ts=_now())
    for g in state.games:
        if g.title == game_title:
            g.attempts.append(attempt)
            return
    update_game(
        state,
        game_title,
        status="pending",
        attempts=[attempt],
    )


def _content_length(headers: httpx.Headers) -> int | None:
    raw = headers.get("Content-Length")
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


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
                    head = client.head(url)
                    if head.status_code < 400:
                        accept_ranges = head.headers.get("Accept-Ranges", "")
                        supports_range = "bytes" in accept_ranges.lower()
                        remote_size = _content_length(head.headers) or remote_size
                except httpx.HTTPError:
                    supports_range = False

                if remote_size is not None and resume_from > remote_size:
                    part.unlink(missing_ok=True)
                    resume_from = 0

            headers: dict[str, str] = {}
            mode = "wb"
            downloaded = 0
            resumed = False
            if resume_from and supports_range:
                headers["Range"] = f"bytes={resume_from}-"
                mode = "ab"
                downloaded = resume_from
                resumed = True

            with client.stream("GET", url, headers=headers) as resp:
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
                if resp.status_code == 200 and headers:
                    mode = "wb"
                    downloaded = 0
                    resumed = False
                elif resp.status_code == 206 and headers:
                    resumed = True
                elif resp.status_code != 200:
                    raise SourceUnavailable(f"{source_name} HTTP {resp.status_code}")

                content_length = _content_length(resp.headers)
                if resp.status_code == 206:
                    total = remote_size or (
                        downloaded + content_length if content_length is not None else None
                    )
                else:
                    total = content_length or remote_size
                    if total is not None and part.exists() and part.stat().st_size > total:
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
        raise SourceUnavailable(f"{source_name} file write error: {exc}") from exc

    try:
        os.replace(part, final)
    except OSError as exc:
        raise SourceUnavailable(f"{source_name} atomic replace failed: {exc}") from exc
    return StreamDownloadResult(path=final, resumed=resumed, bytes_written=downloaded)


def _acquired_filename(state: State, game_title: str, target_dir: Path) -> str | None:
    for entry in state.games:
        if entry.title == game_title and entry.status == "acquired" and entry.filename:
            if (Path(target_dir) / entry.filename).exists():
                return entry.filename
    return None


def skip_if_acquired(
    state: State,
    game_title: str,
    target_dir: Path,
    *,
    event_bus: EventBus | None = None,
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
        return ("unverified", f"archive verification unsupported for {downloaded.suffix}")
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
) -> DownloadResult:
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    skipped = skip_if_acquired(
        state,
        game_title,
        target_dir,
        event_bus=event_bus,
    )
    if skipped is not None:
        return skipped

    if event_bus is not None:
        event_bus.publish(
            GameStartEvent(game=game_title, source=source.name, console=console)
        )

    last_reason: str | None = None
    had_verify_failure = False
    for attempt_num in range(1, MAX_ATTEMPTS_PER_SOURCE + 1):
        try:
            downloaded = source.download(candidate, target_dir, event_bus=event_bus)
        except SourceUnavailable as exc:
            last_reason = str(exc)
            _log.warning(
                "download attempt %s/%s failed for %s via %s: %s",
                attempt_num,
                MAX_ATTEMPTS_PER_SOURCE,
                game_title,
                source.name,
                exc,
            )
            _record_attempt(state, game_title, source.name, f"download_failed: {exc}")
            continue
        except Exception as exc:
            last_reason = f"unexpected: {exc}"
            _log.exception("unexpected download error for %s", game_title)
            _record_attempt(state, game_title, source.name, last_reason)
            continue

        verified = True
        verify_reason: str | None = None
        verification_status = "verified"
        if game is not None:
            rom = _rom_for_verification(game, downloaded.name)
            if rom is not None and (rom.sha1 or rom.crc32 or rom.md5):
                verification_status, verify_reason = _verify_downloaded(
                    downloaded,
                    rom,
                    extract_archives=extract_archives,
                )
                verified = verification_status != "failed"

        if not verified:
            had_verify_failure = True
            last_reason = verify_reason or "hash mismatch"
            _log.warning(
                "verify failed for %s attempt %s: %s",
                game_title,
                attempt_num,
                last_reason,
            )
            _record_attempt(
                state, game_title, source.name, f"verify_failed: {last_reason}"
            )
            try:
                downloaded.unlink()
            except OSError:
                pass
            continue

        if verification_status == "unverified":
            final_filename = sanitize_filename(downloaded.name)
            _record_attempt(
                state,
                game_title,
                source.name,
                f"unverified: {verify_reason or 'not verified'}",
            )
            update_game(
                state,
                game_title,
                status="unverified",
                source=source.name,
                filename=final_filename,
                sha1=candidate.expected_sha1,
                crc32=candidate.expected_crc32,
                size_bytes=candidate.expected_size,
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
                _record_attempt(state, game_title, source.name, last_reason)
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
        _record_attempt(state, game_title, source.name, "success")
        update_game(
            state,
            game_title,
            status="acquired",
            source=source.name,
            filename=sanitized,
            sha1=candidate.expected_sha1,
            crc32=candidate.expected_crc32,
            size_bytes=candidate.expected_size,
        )
        if event_bus is not None:
            event_bus.publish(
                GameDoneEvent(
                    game=game_title,
                    source=source.name,
                    size=candidate.expected_size or 0,
                    sha1=candidate.expected_sha1,
                )
            )
        return DownloadResult(status="acquired", filename=sanitized, source=source.name)

    final_status = "unverified" if had_verify_failure else "failed"
    update_game(
        state,
        game_title,
        status=final_status,
        source=source.name,
    )
    final_reason = last_reason or "exhausted attempts"
    if event_bus is not None:
        event_bus.publish(GameFailedEvent(game=game_title, reason=final_reason))
    return DownloadResult(
        status=final_status,
        source=source.name,
        reason=final_reason,
    )
