from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol, runtime_checkable

from retrofetch.events import EventBus


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


@runtime_checkable
class SourceAdapter(Protocol):
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

    def list_popular(
        self, limit: int, region_priority: list[str] | None = None
    ) -> list[str]: ...
