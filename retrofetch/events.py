from __future__ import annotations

"""Typed progress events and a small synchronous event bus.

Example:
    >>> bus = EventBus()
    >>> seen: list[ProgressEvent] = []
    >>> _handle = bus.subscribe(seen.append)
    >>> bus.publish(GameStartEvent(game="Mario", source="archive_org", console="nes"))
    >>> seen[0]
    GameStartEvent(game='Mario', source='archive_org', console='nes')
"""

from dataclasses import dataclass
import threading
from typing import Callable


@dataclass(frozen=True)
class ProgressEvent:
    """Base class for all orchestrator lifecycle / progress events."""


@dataclass(frozen=True)
class GameStartEvent(ProgressEvent):
    game: str
    source: str
    console: str


@dataclass(frozen=True)
class GameBytesEvent(ProgressEvent):
    game: str
    downloaded: int
    total: int


@dataclass(frozen=True)
class GameDoneEvent(ProgressEvent):
    game: str
    source: str
    size: int
    sha1: str | None


@dataclass(frozen=True)
class GameFailedEvent(ProgressEvent):
    game: str
    reason: str


@dataclass(frozen=True)
class SourceDeadEvent(ProgressEvent):
    source: str
    reason: str


@dataclass(frozen=True)
class RateLimitEvent(ProgressEvent):
    source: str
    retry_after: float


@dataclass(frozen=True)
class CloudflareBlockEvent(ProgressEvent):
    source: str
    status: int


@dataclass(frozen=True)
class DatLoadStartEvent(ProgressEvent):
    console: str
    dat_name: str


@dataclass(frozen=True)
class DatLoadDoneEvent(ProgressEvent):
    console: str
    games_loaded: int


@dataclass(frozen=True)
class ExtractionStartEvent(ProgressEvent):
    filename: str
    format: str


@dataclass(frozen=True)
class ExtractionDoneEvent(ProgressEvent):
    filename: str
    extracted_to: str


class SubscriptionHandle:
    __slots__ = ("_id",)

    def __init__(self, _id: int) -> None:
        self._id = _id


class EventBus:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subscribers: list[tuple[int, Callable[[ProgressEvent], None]]] = []
        self._next_id = 0

    def subscribe(self, callback: Callable[[ProgressEvent], None]) -> SubscriptionHandle:
        with self._lock:
            sid = self._next_id
            self._next_id += 1
            self._subscribers.append((sid, callback))
            return SubscriptionHandle(sid)

    def unsubscribe(self, handle: SubscriptionHandle) -> None:
        with self._lock:
            self._subscribers = [
                (sid, cb) for sid, cb in self._subscribers if sid != handle._id
            ]

    def publish(self, event: ProgressEvent) -> None:
        with self._lock:
            snapshot = list(self._subscribers)
        for _sid, callback in snapshot:
            try:
                callback(event)
            except Exception:
                # best-effort delivery: one faulty subscriber must not block others
                pass
