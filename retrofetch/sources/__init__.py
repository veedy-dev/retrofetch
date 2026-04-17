"""Source adapters for ROM providers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


class SourceUnavailable(Exception):
    """Raised when a source cannot fulfill a request (down, rate-limited, CF-blocked)."""


@dataclass
class DownloadCandidate:
    url: str
    filename: str
    source: str
    expected_size: int | None = None
    expected_sha1: str | None = None
    expected_crc32: str | None = None
    extra: dict[str, object] | None = None


ProgressCallback = Callable[[int, int], None]
