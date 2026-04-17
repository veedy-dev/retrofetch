"""Shared Cloudflare-bypass session."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from retrofetch.sources import SourceUnavailable

_log = logging.getLogger(__name__)

_CF_CHALLENGE_MARKERS = (
    "Just a moment",
    "cf-browser-verification",
    "challenge-platform",
    "cf_chl_opt",
)


class CloudflareBlocked(SourceUnavailable):
    """Raised when Cloudflare returns a challenge page we cannot solve."""


@dataclass
class SourceHealth:
    consecutive_failures: int = 0
    dead: bool = False

    def record_failure(self) -> None:
        self.consecutive_failures += 1
        if self.consecutive_failures >= 5:
            self.dead = True

    def record_success(self) -> None:
        self.consecutive_failures = 0


_health_by_source: dict[str, SourceHealth] = {}


def health(source_name: str) -> SourceHealth:
    if source_name not in _health_by_source:
        _health_by_source[source_name] = SourceHealth()
    return _health_by_source[source_name]


def is_dead(source_name: str) -> bool:
    return health(source_name).dead


def reset_health(source_name: str | None = None) -> None:
    if source_name is None:
        _health_by_source.clear()
    else:
        _health_by_source.pop(source_name, None)


def is_cloudflare_challenge(body: str) -> bool:
    return any(marker in body for marker in _CF_CHALLENGE_MARKERS)


def make_scraper() -> Any:
    try:
        import cloudscraper

        return cloudscraper.create_scraper(
            browser={"browser": "chrome", "platform": "windows", "mobile": False}
        )
    except ImportError as exc:
        raise SourceUnavailable(f"cloudscraper not installed: {exc}") from exc
