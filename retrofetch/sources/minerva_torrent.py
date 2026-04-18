from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import Any

from retrofetch.events import EventBus
from retrofetch.sources import DownloadCandidate, SourceUnavailable

_log = logging.getLogger(__name__)

_SOURCE_NAME = "minerva_torrent"


class MinervaTorrentSource:
    name = _SOURCE_NAME

    def __init__(self, console_entry: dict[str, Any], enabled: bool = True):
        self.console_entry = console_entry
        self.enabled = enabled
        self.minerva_path = console_entry.get("minerva_path")

    def find_url_for_game(
        self,
        title: str,
        region_priority: list[str] | None = None,
    ) -> DownloadCandidate | None:
        if not self.enabled:
            return None
        try:
            importlib.import_module("libtorrent")
        except ImportError as exc:
            raise SourceUnavailable(
                "libtorrent not installed. Install via 'uv pip install libtorrent' or "
                "disable torrent sources via --no-torrent"
            ) from exc
        return None

    def list_popular(
        self, limit: int, region_priority: list[str] | None = None
    ) -> list[str]:
        return []

    def download(
        self,
        candidate: DownloadCandidate,
        dest_dir: Path,
        *,
        event_bus: EventBus | None = None,
    ) -> Path:
        raise SourceUnavailable(
            "Minerva torrent download not implemented in v1. "
            "Use --no-torrent or install libtorrent."
        )
