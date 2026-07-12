from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from retrofetch.downloader import stream_http_download
from retrofetch.events import EventBus
from retrofetch.sources import SourceUnavailable
from retrofetch.sources.minerva_http import MinervaHttpSource


@dataclass(frozen=True)
class BiosFile:
    console: str
    filename: str
    url: str
    size: int | None
    source: str


@dataclass(frozen=True)
class BiosCatalog:
    console: str
    files: list[BiosFile]


_MINERVA_BIOS_PATHS: dict[str, str] = {
    "psx": "Redump/Sony - PlayStation - BIOS Images",
    "ps2": "Redump/Sony - PlayStation 2 - BIOS Images",
    "saturn": "Redump/Sega - Saturn - BIOS Images",
    "segacd": "Redump/Sega - Mega CD & Sega CD - BIOS Images",
    "megacd": "Redump/Sega - Mega CD & Sega CD - BIOS Images",
    "dreamcast": "Redump/Sega - Dreamcast - BIOS Images",
    "3do": "Redump/Panasonic - 3DO Interactive Multiplayer - BIOS Images",
    "pcenginecd": "Redump/NEC - PC Engine CD & TurboGrafx CD - BIOS Images",
    "tg-cd": "Redump/NEC - PC Engine CD & TurboGrafx CD - BIOS Images",
    "neogeocd": "Redump/SNK - Neo Geo CD - BIOS Images",
    "gc": "Redump/Nintendo - GameCube - BIOS Images",
}

_LIBRETRO_IDENTIFIER = "retroarch-system-bios-pack"
_BIOS_EXTENSIONS = (".bin", ".rom", ".pce", ".zip", ".7z", ".iso")
_LIBRETRO_FILE_MAP: dict[str, tuple[str, ...]] = {
    "psx": ("scph5500.bin", "scph5501.bin", "scph5502.bin", "scph1001.bin"),
    "ps2": ("scph39001.bin", "scph10000.bin", "scph70000.bin"),
    "saturn": ("saturn_bios.bin", "mpr-17933.bin", "sega_101.bin"),
    "segacd": ("bios_CD_U.bin", "bios_CD_E.bin", "bios_CD_J.bin"),
    "megacd": ("bios_CD_U.bin", "bios_CD_E.bin", "bios_CD_J.bin"),
    "dreamcast": ("dc_boot.bin", "dc_flash.bin"),
    "3do": ("panafz10.bin", "panafz10-norsa.bin", "panafz1.bin", "goldstar.bin"),
    "pcenginecd": ("syscard3.pce",),
    "tg-cd": ("syscard3.pce",),
    "neogeocd": ("neocd.bin", "uni-bioscd.rom"),
    "gc": ("IPL.bin", "ipl.bin"),
}


class BiosSource:
    def __init__(
        self,
        *,
        minerva_base_url: str = "https://minerva-archive.org/browse/",
        archive_identifier: str = _LIBRETRO_IDENTIFIER,
        archive_metadata_base_url: str = "https://archive.org/metadata/",
        archive_download_base_url: str = "https://archive.org/download/",
        timeout: float = 30.0,
    ) -> None:
        self.minerva_base_url = minerva_base_url
        self.archive_identifier = archive_identifier
        self.archive_metadata_base_url = archive_metadata_base_url.rstrip("/") + "/"
        self.archive_download_base_url = archive_download_base_url.rstrip("/") + "/"
        self.timeout = timeout

    @staticmethod
    def supported_consoles() -> list[str]:
        return sorted(set(_MINERVA_BIOS_PATHS) | set(_LIBRETRO_FILE_MAP))

    @staticmethod
    def _coerce_size(value: Any) -> int | None:
        if value is None:
            return None
        try:
            return int(str(value))
        except ValueError:
            return None

    @staticmethod
    def _quote_identifier(identifier: str) -> str:
        return quote(identifier, safe="")

    @staticmethod
    def _quote_filename(filename: str) -> str:
        return "/".join(quote(part, safe="") for part in filename.split("/"))

    def _archive_url(self, filename: str) -> str:
        return (
            self.archive_download_base_url
            + self._quote_identifier(self.archive_identifier)
            + "/"
            + self._quote_filename(filename)
        )

    def _minerva_files(self, console: str) -> list[BiosFile]:
        path = _MINERVA_BIOS_PATHS.get(console)
        if path is None:
            return []
        source = MinervaHttpSource(
            {"minerva_path": path, "extensions": list(_BIOS_EXTENSIONS)},
            base_url=self.minerva_base_url,
            timeout=self.timeout,
        )
        index_url = source._build_index_url()
        if index_url is None:
            return []
        try:
            catalog_files = source._list_catalog_files(index_url)
        except SourceUnavailable:
            return []
        return [
            BiosFile(
                console=console,
                filename=file.filename,
                url=file.url,
                size=file.size,
                source="minerva_http",
            )
            for file in catalog_files
        ]

    def _archive_files(self, console: str) -> list[BiosFile]:
        wanted = {name.casefold() for name in _LIBRETRO_FILE_MAP.get(console, ())}
        if not wanted:
            return []
        metadata_url = self.archive_metadata_base_url + self._quote_identifier(
            self.archive_identifier
        )
        try:
            with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
                resp = client.get(metadata_url)
        except httpx.HTTPError as exc:
            raise SourceUnavailable(f"libretro BIOS metadata unreachable: {exc}") from exc
        if resp.status_code == 404:
            return []
        if resp.status_code != 200:
            raise SourceUnavailable(f"libretro BIOS metadata HTTP {resp.status_code}")
        payload = resp.json()
        raw_files = payload.get("files", []) if isinstance(payload, dict) else []
        files: list[BiosFile] = []
        for raw in raw_files:
            if not isinstance(raw, dict):
                continue
            name = raw.get("name")
            if not isinstance(name, str):
                continue
            if Path(name).name.casefold() not in wanted:
                continue
            files.append(
                BiosFile(
                    console=console,
                    filename=Path(name).name,
                    url=self._archive_url(name),
                    size=self._coerce_size(raw.get("size")),
                    source="archive_org",
                )
            )
        return files

    def list_files(self, console: str) -> BiosCatalog:
        key = console.casefold()
        if key not in self.supported_consoles():
            raise SourceUnavailable(f"no BIOS source configured for console: {console}")
        files = self._minerva_files(key)
        if not files:
            files = self._archive_files(key)
        files.sort(key=lambda item: (item.size is None, item.size or 0, item.filename))
        return BiosCatalog(console=key, files=files)

    def download(
        self,
        console: str,
        bios_root: Path,
        *,
        limit: int | None = None,
        event_bus: EventBus | None = None,
    ) -> list[Path]:
        catalog = self.list_files(console)
        files = catalog.files
        if limit is not None and limit > 0:
            files = files[:limit]
        target_dir = Path(bios_root) / catalog.console
        target_dir.mkdir(parents=True, exist_ok=True)
        paths: list[Path] = []
        for bios_file in files:
            final = target_dir / bios_file.filename
            if final.exists():
                paths.append(final)
                continue
            result = stream_http_download(
                bios_file.url,
                final,
                event_bus=event_bus,
                event_game=bios_file.filename,
                timeout=self.timeout,
                source_name=bios_file.source,
                expected_size=bios_file.size,
            )
            paths.append(result.path)
        return paths
