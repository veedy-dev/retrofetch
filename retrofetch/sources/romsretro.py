"""romsretro.com source adapter."""

from __future__ import annotations

import logging
from typing import Any

from retrofetch.sources.romsfun import RomsfunSource

_log = logging.getLogger(__name__)

_BASE_URL = "https://romsretro.com/roms/"
_SOURCE_NAME = "romsretro"


class RomsretroSource(RomsfunSource):
    name = _SOURCE_NAME

    def __init__(self, console_entry: dict[str, Any]):
        super().__init__(console_entry, base_url=_BASE_URL)
        self.slug = console_entry.get("romsretro_slug")
