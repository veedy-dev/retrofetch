"""In-memory download state, independent of whichever screen is visible."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from time import monotonic
from typing import Any

from textual.message import Message

from retrofetch.tui import messages as m


def format_speed(bps: float) -> str:
    if bps >= 1024 * 1024:
        return f"{bps / (1024 * 1024):.1f} MB/s"
    return f"{bps / 1024:.0f} KB/s"


def format_bytes(value: float) -> str:
    size = max(0.0, value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return "0 B"


def format_eta(seconds: int) -> str:
    hours, remainder = divmod(max(0, seconds), 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


@dataclass
class DownloadItem:
    title: str
    source: str = ""
    stage: str = "Starting"
    detail: str = ""
    downloaded: int = 0
    total: int = 0
    speed_bps: float = 0.0
    eta_seconds: int | None = None
    seeds: int | None = None
    peers: int | None = None
    _last_ts: float = field(default_factory=monotonic, repr=False)
    _last_bytes: int = field(default=0, repr=False)


@dataclass
class DownloadRecord:
    title: str
    outcome: str
    detail: str = ""
    verification: str = ""
    source: str = ""


@dataclass
class DownloadSession:
    console_entry: dict[str, Any]
    wantlist: list[str]
    dry_run: bool = False
    active: dict[str, DownloadItem] = field(default_factory=dict)
    recent: deque[DownloadRecord] = field(default_factory=lambda: deque(maxlen=50))
    notices: deque[str] = field(default_factory=lambda: deque(maxlen=50))
    title_status: dict[str, str] = field(default_factory=dict)
    running: bool = True
    cancelling: bool = False
    unread: bool = False
    error: str | None = None
    verification_detail: str = ""
    revision: int = 0
    history_revision: int = 0
    status_revision: int = 0
    acquired: int = 0
    unverified: int = 0
    failed: int = 0
    skipped: int = 0
    cancelled: int = 0
    reviewed: int = 0
    _terminal: set[str] = field(default_factory=set, repr=False)

    @property
    def shortname(self) -> str:
        return str(self.console_entry["shortname"])

    @property
    def completed_count(self) -> int:
        return self.acquired + self.unverified + self.skipped

    @property
    def processed_count(self) -> int:
        return self.completed_count + self.failed + self.cancelled + self.reviewed

    @property
    def progress(self) -> float:
        # A full transfer is still not ready until verification/extraction finishes.
        return float(min(self.processed_count, len(self.wantlist)))

    @property
    def summary(self) -> str:
        if self.error:
            return f"Download failed: {self.error}"
        if self.cancelling and self.running:
            return "Stopping safely; waiting for download cleanup."
        if self.dry_run:
            return f"Dry run {'running' if self.running else 'complete'}: {self.processed_count} / {len(self.wantlist)} reviewed; no files downloaded."
        parts = [f"{self.acquired + self.unverified} downloaded"]
        for count, label in (
            (self.skipped, "already present"),
            (self.failed, "failed"),
            (self.cancelled, "cancelled"),
        ):
            if count:
                parts.append(f"{count} {label}")
        return (
            ("In progress: " if self.running else "Finished: ") + ", ".join(parts) + "."
        )

    def apply(self, message: Message) -> None:
        if not self.running:
            return
        if isinstance(
            message,
            (
                m.GameStart,
                m.GameBytes,
                m.GameStage,
                m.GameDone,
                m.GameUnverified,
                m.GameFailed,
                m.GameSkipped,
                m.GameCancelled,
            ),
        ):
            key = message.item_id or message.game
            if key in self._terminal:
                return
            previous_status = self.title_status.get(message.game)
            if isinstance(message, (m.GameStart, m.GameBytes, m.GameStage)):
                item = self.active.get(key)
                if item is None or isinstance(message, m.GameStart):
                    item = DownloadItem(message.game)
                    self.active[key] = item
                if isinstance(message, m.GameStart):
                    item.source = message.source
                elif isinstance(message, m.GameStage):
                    item.stage = message.stage
                    item.detail = message.detail or ""
                else:
                    now = monotonic()
                    elapsed = now - item._last_ts
                    item.downloaded = max(0, message.downloaded)
                    item.total = max(0, message.total)
                    item.stage = "Downloading"
                    if message.speed_bps is not None:
                        item.speed_bps = float(max(0, message.speed_bps))
                    elif elapsed >= 0.1:
                        item.speed_bps = (
                            max(0, item.downloaded - item._last_bytes) / elapsed
                        )
                    if message.speed_bps is not None or elapsed >= 0.1:
                        item._last_bytes, item._last_ts = item.downloaded, now
                    item.eta_seconds = message.eta_seconds
                    item.seeds, item.peers = message.seeds, message.peers
                self.title_status[message.game] = item.stage
            else:
                item = self.active.pop(key, None)
                source = getattr(message, "source", item.source if item else "")
                detail = getattr(message, "reason", "") or ""
                verification = ""
                if isinstance(message, m.GameDone):
                    outcome = (
                        "dry-run"
                        if self.dry_run or source == "dry-run"
                        else "downloaded"
                    )
                    if outcome == "dry-run":
                        self.reviewed += 1
                    else:
                        self.acquired += 1
                    verification = (
                        "not checked (dry run)" if outcome == "dry-run" else "verified"
                    )
                elif isinstance(message, m.GameUnverified):
                    self.unverified += 1
                    outcome, verification = "downloaded", "unverified"
                elif isinstance(message, m.GameFailed):
                    self.failed += 1
                    outcome = "failed"
                elif isinstance(message, m.GameSkipped):
                    self.skipped += 1
                    outcome = "skipped"
                    verification = (
                        "existing artifact validated" if message.filename else ""
                    )
                else:
                    self.cancelled += 1
                    outcome = "cancelled"
                self._terminal.add(key)
                self.recent.append(
                    DownloadRecord(message.game, outcome, detail, verification, source)
                )
                self.title_status[message.game] = outcome.replace("-", " ").capitalize()
                self.history_revision += 1
            if self.title_status.get(message.game) != previous_status:
                self.status_revision += 1
        elif isinstance(message, m.DatLoadDone):
            self.verification_detail = (
                message.detail or f"DAT {message.status}: {message.games_loaded} games."
            )
            self.history_revision += 1
        elif isinstance(message, (m.SourceDead, m.RateLimit, m.CloudflareBlock)):
            if isinstance(message, m.SourceDead):
                notice = f"{message.source}: {message.reason}"
            elif isinstance(message, m.RateLimit):
                notice = (
                    f"{message.source}: rate limited; retry in {message.retry_after:g}s"
                )
            else:
                notice = f"{message.source}: Cloudflare blocked request (HTTP {message.status})"
            self.notices.append(notice)
            self.history_revision += 1
        elif isinstance(message, (m.DownloadComplete, m.DownloadCrashed)):
            if isinstance(message, m.DownloadComplete):
                report = message.report
                for name in (
                    "acquired",
                    "unverified",
                    "failed",
                    "skipped",
                    "cancelled",
                ):
                    setattr(self, name, getattr(report, name))
                if self.dry_run:
                    self.reviewed = report.attempted
                self.error = report.error
                if report.skip_reason:
                    self.notices.append(report.skip_reason)
            else:
                self.error = message.exc
            self.running = False
            self.active.clear()
            self.unread = True
            self.history_revision += 1
        else:
            return
        self.revision += 1
