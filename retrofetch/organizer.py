"""File organizer with collision handling."""

from __future__ import annotations

import hashlib
import logging
import re
import shutil
from pathlib import Path

from retrofetch.sanitize import make_long_path, sanitize_filename

_log = logging.getLogger(__name__)

_DISC_PATTERN = re.compile(r"\s*\((?:Disc|Disk)\s*\d+[^)]*\)", re.IGNORECASE)


class PlaceResult:
    def __init__(self, status: str, final_path: Path, reason: str | None = None):
        self.status = status
        self.final_path = final_path
        self.reason = reason


def strip_disc_marker(title: str) -> str:
    return _DISC_PATTERN.sub("", title).strip()


def _file_sha1(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def place_file(
    extracted: Path,
    target_dir: Path,
    canonical_name: str,
) -> PlaceResult:
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    safe_name = sanitize_filename(canonical_name)
    final = target_dir / safe_name
    final_long = make_long_path(final)
    if final.exists():
        existing_sha = _file_sha1(final)
        incoming_sha = _file_sha1(extracted)
        if existing_sha == incoming_sha:
            try:
                Path(extracted).unlink()
            except OSError:
                pass
            return PlaceResult(status="already_present", final_path=final)
        stem = final.stem
        ext = final.suffix
        suffix_num = 2
        while True:
            candidate = target_dir / f"{stem} ({suffix_num}){ext}"
            if not candidate.exists():
                final = candidate
                final_long = make_long_path(final)
                break
            suffix_num += 1
        _log.warning(
            "collision with different hash at %s; using %s instead",
            safe_name,
            final.name,
        )
    shutil.move(str(extracted), str(final_long))
    return PlaceResult(status="placed", final_path=final)
