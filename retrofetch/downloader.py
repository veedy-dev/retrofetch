"""Download orchestrator with resume and extraction."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from retrofetch.dat import GameEntry, Rom, VerifyResult, verify_file
from retrofetch.extractor import ExtractionError, extract_archive, is_archive
from retrofetch.sanitize import sanitize_filename
from retrofetch.sources import DownloadCandidate, ProgressCallback, SourceUnavailable
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
        progress_cb: ProgressCallback | None = None,
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


def download_game(
    source: Source,
    candidate: DownloadCandidate,
    target_dir: Path,
    game: GameEntry | None,
    game_title: str,
    state: State,
    progress_cb: ProgressCallback | None = None,
) -> DownloadResult:
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    last_reason: str | None = None
    had_verify_failure = False
    for attempt_num in range(1, MAX_ATTEMPTS_PER_SOURCE + 1):
        try:
            downloaded = source.download(candidate, target_dir, progress_cb)
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
        if game is not None:
            rom = _rom_for_verification(game, downloaded.name)
            if rom is not None and (rom.sha1 or rom.crc32 or rom.md5):
                result: VerifyResult = verify_file(downloaded, rom)
                verified = result.matched
                verify_reason = result.reason

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

        final_filename = downloaded.name
        if is_archive(downloaded):
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
        return DownloadResult(status="acquired", filename=sanitized, source=source.name)

    final_status = "unverified" if had_verify_failure else "failed"
    update_game(
        state,
        game_title,
        status=final_status,
        source=source.name,
    )
    return DownloadResult(
        status=final_status,
        source=source.name,
        reason=last_reason or "exhausted attempts",
    )
