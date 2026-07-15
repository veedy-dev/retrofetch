from __future__ import annotations

from dataclasses import dataclass
import hashlib
import posixpath
import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urljoin, urlsplit

import httpx

from retrofetch.catalog import CatalogEntry, CatalogFile
from retrofetch.events import EventBus
from retrofetch.sources import DownloadCandidate, SourceUnavailable
from retrofetch.sources.minerva_http import MinervaHttpSource, effective_minerva_paths

_SOURCE_NAME = "minerva_torrent"
_ASSETS_BASE_URL = "https://minerva-archive.org/assets/Minerva_Myrient_v0.3/"
_MAX_TORRENT_BYTES = 32 * 1024 * 1024
_MAX_TORRENT_FILES = 50_000
_MAX_PATH_DEPTH = 32
_MAX_PATH_BYTES = 4096
_MAX_COLLECTION_BYTES = 100 * 1024**4
_MAX_BENCODE_DEPTH = 64
_MAX_BENCODE_ITEMS = 100_000
_HEX_RE = re.compile(r"^[0-9a-fA-F]+$")
_DRIVE_RE = re.compile(r"^[A-Za-z]:")
_WINDOWS_RESERVED_NAMES = {
    "aux",
    "clock$",
    "con",
    "conin$",
    "conout$",
    "nul",
    "prn",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}


@dataclass(frozen=True)
class _TorrentFile:
    index: int
    path: str
    size: int
    sha1: str | None = None
    crc32: str | None = None
    md5: str | None = None


@dataclass(frozen=True)
class _TorrentMetadata:
    name: str
    infohash: str
    files: tuple[_TorrentFile, ...]


class _BencodeReader:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0
        self.items = 0
        self.info_range: tuple[int, int] | None = None

    def read(self, depth: int = 0) -> object:
        if depth > _MAX_BENCODE_DEPTH or self.pos >= len(self.data):
            raise ValueError("invalid bencode nesting")
        self.items += 1
        if self.items > _MAX_BENCODE_ITEMS:
            raise ValueError("too many bencode values")

        marker = self.data[self.pos : self.pos + 1]
        if marker == b"i":
            return self._integer()
        if marker == b"l":
            self.pos += 1
            list_values: list[object] = []
            while self._marker() != b"e":
                list_values.append(self.read(depth + 1))
            self.pos += 1
            return list_values
        if marker == b"d":
            self.pos += 1
            dict_values: dict[bytes, object] = {}
            while self._marker() != b"e":
                key = self.read(depth + 1)
                if not isinstance(key, bytes) or key in dict_values:
                    raise ValueError("invalid bencode dictionary key")
                value_start = self.pos
                dict_values[key] = self.read(depth + 1)
                if depth == 0 and key == b"info":
                    self.info_range = (value_start, self.pos)
            self.pos += 1
            return dict_values
        if marker.isdigit():
            return self._bytes()
        raise ValueError("invalid bencode marker")

    def _marker(self) -> bytes:
        if self.pos >= len(self.data):
            raise ValueError("truncated bencode value")
        return self.data[self.pos : self.pos + 1]

    def _integer(self) -> int:
        end = self.data.find(b"e", self.pos + 1)
        if end < 0:
            raise ValueError("truncated bencode integer")
        raw = self.data[self.pos + 1 : end]
        if not raw or raw == b"-0" or (raw.startswith(b"0") and len(raw) > 1):
            raise ValueError("invalid bencode integer")
        try:
            value = int(raw)
        except ValueError as exc:
            raise ValueError("invalid bencode integer") from exc
        self.pos = end + 1
        return value

    def _bytes(self) -> bytes:
        colon = self.data.find(b":", self.pos)
        if colon < 0:
            raise ValueError("truncated bencode string")
        raw_length = self.data[self.pos : colon]
        if not raw_length or (raw_length.startswith(b"0") and len(raw_length) > 1):
            raise ValueError("invalid bencode string length")
        try:
            length = int(raw_length)
        except ValueError as exc:
            raise ValueError("invalid bencode string length") from exc
        start = colon + 1
        end = start + length
        if length < 0 or end > len(self.data):
            raise ValueError("truncated bencode string")
        self.pos = end
        return self.data[start:end]


def _safe_path(raw: str) -> str:
    if not raw or raw.startswith(("/", "\\")) or "\\" in raw:
        raise ValueError("unsafe torrent path")
    while raw.startswith("./"):
        raw = raw[2:]
    parts = raw.split("/")
    if (
        not parts
        or len(parts) > _MAX_PATH_DEPTH
        or any(not part or part in {".", ".."} for part in parts)
        or _DRIVE_RE.match(parts[0])
        or any(
            ":" in part
            or part.endswith((".", " "))
            or part.split(".", 1)[0].casefold() in _WINDOWS_RESERVED_NAMES
            for part in parts
        )
        or any(any(ord(char) < 32 for char in part) for part in parts)
    ):
        raise ValueError("unsafe torrent path")
    normalized = "/".join(parts)
    if len(normalized.encode("utf-8")) > _MAX_PATH_BYTES:
        raise ValueError("torrent path is too long")
    return normalized


def _text(value: object, label: str) -> str:
    if not isinstance(value, bytes):
        raise ValueError(f"invalid {label}")
    try:
        return value.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"invalid UTF-8 {label}") from exc


def _hash(value: object, byte_length: int) -> str | None:
    if not isinstance(value, bytes):
        return None
    if len(value) == byte_length:
        return value.hex()
    try:
        text = value.decode("ascii")
    except UnicodeDecodeError:
        return None
    if len(text) == byte_length * 2 and _HEX_RE.fullmatch(text):
        return text.lower()
    return None


def _parse_torrent_metadata(data: bytes) -> _TorrentMetadata:
    if len(data) > _MAX_TORRENT_BYTES:
        raise SourceUnavailable(
            f"Minerva torrent metadata exceeds {_MAX_TORRENT_BYTES} bytes",
            retryable=False,
        )
    try:
        reader = _BencodeReader(data)
        root = reader.read()
        if reader.pos != len(data) or not isinstance(root, dict):
            raise ValueError("invalid torrent root")
        info = root.get(b"info")
        if not isinstance(info, dict) or reader.info_range is None:
            raise ValueError("torrent has no info dictionary")
        info_start, info_end = reader.info_range
        infohash = hashlib.sha1(data[info_start:info_end]).hexdigest()
        name = _safe_path(_text(info.get(b"name"), "torrent name"))

        raw_files = info.get(b"files")
        if raw_files is None:
            raw_files = [{b"length": info.get(b"length"), b"path": [info.get(b"name")]}]
        if not isinstance(raw_files, list) or not raw_files:
            raise ValueError("torrent has no files")
        if len(raw_files) > _MAX_TORRENT_FILES:
            raise ValueError("torrent has too many files")

        files: list[_TorrentFile] = []
        total_size = 0
        for index, raw_file in enumerate(raw_files):
            if not isinstance(raw_file, dict):
                raise ValueError("invalid torrent file")
            size = raw_file.get(b"length")
            raw_path = raw_file.get(b"path")
            if not isinstance(size, int) or size < 0 or not isinstance(raw_path, list):
                raise ValueError("invalid torrent file")
            path = _safe_path(
                "/".join(_text(part, "torrent path") for part in raw_path)
            )
            total_size += size
            if total_size > _MAX_COLLECTION_BYTES:
                raise ValueError("torrent collection is too large")
            files.append(
                _TorrentFile(
                    index=index,
                    path=path,
                    size=size,
                    sha1=_hash(raw_file.get(b"sha1"), 20),
                    crc32=_hash(raw_file.get(b"crc32"), 4),
                    md5=_hash(raw_file.get(b"md5sum"), 16),
                )
            )
        return _TorrentMetadata(name=name, infohash=infohash, files=tuple(files))
    except SourceUnavailable:
        raise
    except (TypeError, ValueError) as exc:
        raise SourceUnavailable(
            f"Invalid Minerva torrent metadata: {exc}", retryable=False
        ) from exc


class MinervaTorrentSource:
    name = _SOURCE_NAME

    def __init__(self, console_entry: dict[str, Any], enabled: bool = True):
        self.console_entry = console_entry
        self.enabled = enabled
        minerva_paths = effective_minerva_paths(console_entry)
        self.minerva_path = minerva_paths[0] if minerva_paths else None
        self.timeout = 30.0
        self._catalog = MinervaHttpSource(console_entry)
        self._metadata_cache: dict[str, tuple[bytes, _TorrentMetadata]] = {}

    def _collection_torrent_url(self, minerva_path: str | None = None) -> str | None:
        selected_path = self.minerva_path if minerva_path is None else minerva_path
        if not selected_path:
            return None
        try:
            path = _safe_path(str(selected_path).strip("/"))
        except ValueError as exc:
            raise SourceUnavailable(
                f"Invalid Minerva path: {exc}", retryable=False
            ) from exc
        filename = f"Minerva_Myrient - {' - '.join(path.split('/'))}.torrent"
        return urljoin(_ASSETS_BASE_URL, quote(filename, safe="-_."))

    @staticmethod
    def _catalog_full_path(catalog_file: CatalogFile) -> str | None:
        parts = urlsplit(catalog_file.url)
        if parts.path.rstrip("/") != "/rom":
            return None
        names = parse_qs(parts.query).get("name") or []
        if len(names) != 1:
            return None
        try:
            path = _safe_path(names[0])
        except ValueError as exc:
            raise SourceUnavailable(
                f"Invalid Minerva catalog path: {exc}", retryable=False
            ) from exc
        if posixpath.basename(path) != catalog_file.filename:
            raise SourceUnavailable(
                "Minerva catalog filename does not match its full path", retryable=False
            )
        return path

    def _fetch_torrent_bytes(self, url: str) -> bytes:
        try:
            with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
                with client.stream("GET", url) as response:
                    if response.status_code == 404:
                        raise SourceUnavailable(
                            f"Minerva collection torrent not found: {url}",
                            retryable=False,
                        )
                    if response.status_code != 200:
                        raise SourceUnavailable(
                            f"Minerva torrent returned HTTP {response.status_code}"
                        )
                    raw_length = response.headers.get("content-length")
                    if raw_length and int(raw_length) > _MAX_TORRENT_BYTES:
                        raise SourceUnavailable(
                            f"Minerva torrent metadata exceeds {_MAX_TORRENT_BYTES} bytes",
                            retryable=False,
                        )
                    data = bytearray()
                    for chunk in response.iter_bytes():
                        data.extend(chunk)
                        if len(data) > _MAX_TORRENT_BYTES:
                            raise SourceUnavailable(
                                f"Minerva torrent metadata exceeds {_MAX_TORRENT_BYTES} bytes",
                                retryable=False,
                            )
                    return bytes(data)
        except SourceUnavailable:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            raise SourceUnavailable(f"Minerva torrent unreachable: {exc}") from exc

    def _metadata(self, url: str) -> tuple[bytes, _TorrentMetadata]:
        cached = self._metadata_cache.get(url)
        if cached is not None:
            return cached
        content = self._fetch_torrent_bytes(url)
        cached = (content, _parse_torrent_metadata(content))
        self._metadata_cache[url] = cached
        return cached

    def _get_entry(
        self, title: str, region_priority: list[str] | None
    ) -> tuple[str, CatalogEntry] | None:
        return self._catalog.get_entry_with_root(title, region_priority)

    def find_url_for_game(
        self,
        title: str,
        region_priority: list[str] | None = None,
    ) -> DownloadCandidate | None:
        if not self.enabled:
            return None
        resolved = self._get_entry(title, region_priority)
        if resolved is None:
            return None
        root, entry = resolved
        if len(entry.files) != 1:
            return None
        full_path = self._catalog_full_path(entry.files[0])
        torrent_url = self._collection_torrent_url(root)
        if full_path is None or torrent_url is None:
            return None

        root = _safe_path(root.strip("/"))
        if full_path != root and not full_path.startswith(root + "/"):
            raise SourceUnavailable(
                "Minerva catalog path escapes its console collection", retryable=False
            )
        torrent_bytes, metadata = self._metadata(torrent_url)
        matches = [
            file
            for file in metadata.files
            if file.path.casefold() == full_path.casefold()
        ]
        if len(matches) > 1:
            raise SourceUnavailable(
                "Minerva torrent contains a case-fold duplicate of the selected path",
                retryable=False,
            )
        if len(matches) != 1 or matches[0].path != full_path:
            return None
        artifact = matches[0]
        return DownloadCandidate(
            url=torrent_url,
            filename=posixpath.basename(artifact.path),
            source=_SOURCE_NAME,
            expected_size=artifact.size,
            expected_sha1=artifact.sha1,
            expected_crc32=artifact.crc32,
            extra={
                "transport": "torrent",
                "torrent_url": torrent_url,
                "torrent_infohash": metadata.infohash,
                "torrent_internal_path": artifact.path,
                "torrent_file_index": artifact.index,
                "torrent_name": metadata.name,
                "torrent_bytes": torrent_bytes,
                "minerva_full_path": full_path,
                "minerva_path": root,
                "catalog_title": entry.title,
                "catalog_region": entry.region,
                "artifact_md5": artifact.md5,
            },
        )

    def list_popular(
        self, limit: int, region_priority: list[str] | None = None
    ) -> list[str]:
        if not self.enabled:
            return []
        return self._catalog.list_popular(limit, region_priority)

    def download(
        self,
        candidate: DownloadCandidate,
        dest_dir: Path,
        *,
        event_bus: EventBus | None = None,
    ) -> Path:
        raise SourceUnavailable(
            "Minerva torrent transfer requires the qBittorrent coordinator",
            retryable=False,
        )
