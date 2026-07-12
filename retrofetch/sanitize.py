"""Filename sanitization and Windows long-path utilities."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

_FORBIDDEN = re.compile(r"[\x00-\x1f<>:\"/\\|?*]")
_COLON = re.compile(r"\s*:\s*")
_MULTI_DASH = re.compile(r"-{2,}")
_MULTI_SPACE = re.compile(r"\s{2,}")
_REGION_SUFFIX = re.compile(r"(\s+\([^)]+\))$")
_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
_MAX_WINDOWS_PATH = 240


def _split_extension(name: str) -> tuple[str, str]:
    stem, dot, ext_raw = name.rpartition(".")
    if not dot or not ext_raw or not re.fullmatch(r"[A-Za-z0-9]{1,10}", ext_raw):
        return name, ""
    return stem, dot + ext_raw


def _truncate_with_region(title: str, region: str, ext: str, limit: int) -> str:
    max_title = limit - len(region) - len(ext)
    if max_title < 1:
        max_title = 1
    truncated = title[:max_title].rstrip(". ")
    if not truncated:
        truncated = "_"
    return f"{truncated}{region}{ext}"


def _absolute_len(path: Path) -> int:
    return len(os.path.abspath(str(path)))


def sanitize_filename(name: str, dest_dir: str | None = None) -> str:
    if not name:
        return "_"
    name = name.rstrip(". ")
    if not name:
        return "_"
    stem, ext = _split_extension(name)
    cleaned = _COLON.sub(" - ", stem)
    cleaned = _FORBIDDEN.sub("-", cleaned)
    cleaned = _MULTI_DASH.sub("-", cleaned)
    cleaned = _MULTI_SPACE.sub(" ", cleaned)
    cleaned = cleaned.rstrip(". ").strip()
    region = ""
    match = _REGION_SUFFIX.search(cleaned)
    if match:
        region = match.group(1)
        cleaned = cleaned[: match.start()].rstrip(". ")
    if not cleaned:
        cleaned = "_"
    if cleaned.upper() in _RESERVED:
        cleaned += "_"
    result = f"{cleaned}{region}{ext}"
    limit = _MAX_WINDOWS_PATH
    if dest_dir is None:
        if len(result) > limit:
            result = _truncate_with_region(cleaned, region, ext, limit)
        return result
    target_dir = Path(dest_dir)
    overflow = _absolute_len(target_dir / result) - limit
    if overflow > 0:
        result = _truncate_with_region(cleaned, region, ext, len(result) - overflow)
        overflow = _absolute_len(target_dir / result) - limit
        if overflow > 0:
            result = _truncate_with_region(cleaned, region, ext, len(result) - overflow)
        return result
    return result


def sanitize_path_components(parts: list[str]) -> list[str]:
    return [sanitize_filename(p) for p in parts]


def ensure_long_path_enabled() -> bool:
    if sys.platform != "win32":
        return True
    try:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\FileSystem",
        )
        value, _ = winreg.QueryValueEx(key, "LongPathsEnabled")
        return bool(value)
    except (OSError, ImportError):
        return False


def make_long_path(path: Path) -> Path:
    if sys.platform != "win32":
        return path
    s = str(path)
    if s.startswith("\\\\?\\"):
        return path
    if len(s) <= 240:
        return path
    abs_s = os.path.abspath(s)
    if abs_s.startswith("\\\\"):
        return Path("\\\\?\\UNC\\" + abs_s[2:])
    return Path("\\\\?\\" + abs_s)
