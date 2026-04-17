"""Filename sanitization and Windows long-path utilities."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

_FORBIDDEN = re.compile(r'[<>"/\\|?*]')
_COLON = re.compile(r"\s*:\s*")
_MULTI_DASH = re.compile(r"-{2,}")
_MULTI_SPACE = re.compile(r"\s{2,}")
_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
_MAX_NAME_LEN = 240


def sanitize_filename(name: str) -> str:
    if not name:
        return "_"
    name = name.rstrip(". ")
    if not name:
        return "_"
    stem, dot, ext_raw = name.rpartition(".")
    if not dot or not ext_raw or not re.fullmatch(r"[A-Za-z0-9]{1,10}", ext_raw):
        stem, ext = name, ""
    else:
        ext = dot + ext_raw
    cleaned = _COLON.sub(" - ", stem)
    cleaned = _FORBIDDEN.sub("-", cleaned)
    cleaned = _MULTI_DASH.sub("-", cleaned)
    cleaned = _MULTI_SPACE.sub(" ", cleaned)
    cleaned = cleaned.rstrip(". ").strip()
    if cleaned.upper() in _RESERVED:
        cleaned = "_" + cleaned
    max_stem = _MAX_NAME_LEN - len(ext)
    if max_stem < 1:
        ext = ext[: _MAX_NAME_LEN // 2]
        max_stem = _MAX_NAME_LEN - len(ext)
    if len(cleaned) > max_stem:
        cleaned = cleaned[:max_stem]
    if not cleaned:
        cleaned = "_"
    return cleaned + ext


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
