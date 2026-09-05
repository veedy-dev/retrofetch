from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from textual.message import Message  # pyright: ignore[reportMissingImports]

from retrofetch.coverage import CoverageReport
from retrofetch.events import (
    CloudflareBlockEvent,
    DatLoadDoneEvent,
    DatLoadStartEvent,
    EventBus,
    ExtractionDoneEvent,
    ExtractionStartEvent,
    GameBytesEvent,
    GameCancelledEvent,
    GameDoneEvent,
    GameFailedEvent,
    GameSkippedEvent,
    GameStageEvent,
    GameStartEvent,
    GameUnverifiedEvent,
    ProgressEvent,
    RateLimitEvent,
    SourceDeadEvent,
    SubscriptionHandle,
)
from retrofetch.orchestrator import RunReport


class GameStart(Message):
    def __init__(
        self, game: str, source: str, console: str, item_id: str | None = None
    ) -> None:
        self.game = game
        self.source = source
        self.console = console
        self.item_id = item_id
        super().__init__()


class GameBytes(Message):
    def __init__(
        self,
        game: str,
        downloaded: int,
        total: int,
        item_id: str | None = None,
        speed_bps: int | None = None,
        eta_seconds: int | None = None,
        seeds: int | None = None,
        peers: int | None = None,
    ) -> None:
        self.game = game
        self.downloaded = downloaded
        self.total = total
        self.item_id = item_id
        self.speed_bps = speed_bps
        self.eta_seconds = eta_seconds
        self.seeds = seeds
        self.peers = peers
        super().__init__()


class GameStage(Message):
    def __init__(
        self,
        game: str,
        stage: str,
        detail: str | None = None,
        item_id: str | None = None,
    ) -> None:
        self.game = game
        self.stage = stage
        self.detail = detail
        self.item_id = item_id
        super().__init__()


class GameDone(Message):
    def __init__(
        self,
        game: str,
        source: str,
        size: int,
        sha1: str | None,
        item_id: str | None = None,
    ) -> None:
        self.game = game
        self.source = source
        self.size = size
        self.sha1 = sha1
        self.item_id = item_id
        super().__init__()


class GameUnverified(Message):
    def __init__(
        self,
        game: str,
        source: str,
        reason: str | None = None,
        item_id: str | None = None,
    ) -> None:
        self.game = game
        self.source = source
        self.reason = reason
        self.item_id = item_id
        super().__init__()


class GameFailed(Message):
    def __init__(self, game: str, reason: str, item_id: str | None = None) -> None:
        self.game = game
        self.reason = reason
        self.item_id = item_id
        super().__init__()


class GameSkipped(Message):
    def __init__(
        self,
        game: str,
        reason: str,
        filename: str | None = None,
        item_id: str | None = None,
    ) -> None:
        self.game = game
        self.reason = reason
        self.filename = filename
        self.item_id = item_id
        super().__init__()


class GameCancelled(Message):
    def __init__(
        self, game: str, reason: str | None = None, item_id: str | None = None
    ) -> None:
        self.game = game
        self.reason = reason
        self.item_id = item_id
        super().__init__()


class SourceDead(Message):
    def __init__(self, source: str, reason: str) -> None:
        self.source = source
        self.reason = reason
        super().__init__()


class RateLimit(Message):
    def __init__(self, source: str, retry_after: float) -> None:
        self.source = source
        self.retry_after = retry_after
        super().__init__()


class CloudflareBlock(Message):
    def __init__(self, source: str, status: int) -> None:
        self.source = source
        self.status = status
        super().__init__()


class DatLoadStart(Message):
    def __init__(self, console: str, dat_name: str) -> None:
        self.console = console
        self.dat_name = dat_name
        super().__init__()


class DatLoadDone(Message):
    def __init__(
        self,
        console: str,
        games_loaded: int,
        status: str = "loaded",
        detail: str | None = None,
    ) -> None:
        self.console = console
        self.games_loaded = games_loaded
        self.status = status
        self.detail = detail
        super().__init__()


class ExtractionStart(Message):
    def __init__(self, filename: str, format: str) -> None:
        self.filename = filename
        self.format = format
        super().__init__()


class ExtractionDone(Message):
    def __init__(self, filename: str, extracted_to: str) -> None:
        self.filename = filename
        self.extracted_to = extracted_to
        super().__init__()


if TYPE_CHECKING:
    from retrofetch.tui.downloads import DownloadSession
    from retrofetch.tui.workers.download_worker import TorrentSetupGate


class QueueChanged(Message):
    def __init__(self, console: str) -> None:
        self.console = console
        super().__init__()


class DownloadUpdate(Message):
    def __init__(self, session: DownloadSession, message: Message) -> None:
        self.session = session
        self.message = message
        super().__init__()


class EventBusBridge:
    """Translates EventBus ProgressEvents into Textual Messages.

    The receiver must be thread-safe (normally ``App.post_message``).
    """

    _TRANSLATIONS: ClassVar[list[tuple[type[ProgressEvent], type[Message]]]] = [
        (GameStartEvent, GameStart),
        (GameBytesEvent, GameBytes),
        (GameStageEvent, GameStage),
        (GameDoneEvent, GameDone),
        (GameUnverifiedEvent, GameUnverified),
        (GameFailedEvent, GameFailed),
        (GameSkippedEvent, GameSkipped),
        (GameCancelledEvent, GameCancelled),
        (SourceDeadEvent, SourceDead),
        (RateLimitEvent, RateLimit),
        (CloudflareBlockEvent, CloudflareBlock),
        (DatLoadStartEvent, DatLoadStart),
        (DatLoadDoneEvent, DatLoadDone),
        (ExtractionStartEvent, ExtractionStart),
        (ExtractionDoneEvent, ExtractionDone),
    ]

    def __init__(self, receive: Callable[[Message], object], bus: EventBus) -> None:
        self._receive = receive
        self._bus = bus
        self._handle: SubscriptionHandle | None = None

    def start(self) -> None:
        """Subscribe to the event bus. Safe to call once per bridge instance."""
        self._handle = self._bus.subscribe(self._on_event)

    def stop(self) -> None:
        """Unsubscribe. Idempotent."""
        if self._handle is not None:
            self._bus.unsubscribe(self._handle)
            self._handle = None

    def _on_event(self, event: ProgressEvent) -> None:
        for event_cls, msg_cls in self._TRANSLATIONS:
            if isinstance(event, event_cls):
                kwargs = {
                    name: getattr(event, name)
                    for name in event_cls.__dataclass_fields__
                }
                # EventBus isolates receiver failures, including app teardown.
                self._receive(msg_cls(**kwargs))
                return


class DownloadComplete(Message):
    def __init__(self, report: RunReport) -> None:
        self.report = report
        super().__init__()


class DownloadCrashed(Message):
    def __init__(self, exc: str) -> None:
        self.exc = exc
        super().__init__()


class TorrentSetupRequired(Message):
    def __init__(self, request: TorrentSetupGate) -> None:
        self.request = request
        super().__init__()


class CoverageReady(Message):
    def __init__(self, report: CoverageReport) -> None:
        self.report = report
        super().__init__()


class WantlistReady(Message):
    def __init__(
        self,
        console: str,
        titles: list[str],
        from_cache: bool,
        request_id: int | None = None,
    ) -> None:
        self.console = console
        self.titles = titles
        self.from_cache = from_cache
        self.request_id = request_id
        super().__init__()


class WantlistFailed(Message):
    def __init__(
        self, console: str, reason: str, request_id: int | None = None
    ) -> None:
        self.console = console
        self.reason = reason
        self.request_id = request_id
        super().__init__()


class SetupComplete(Message):
    def __init__(self, config_path: Path) -> None:
        self.config_path = config_path
        super().__init__()
