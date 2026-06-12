"""Configuration helpers.

All YAML I/O for user-facing config files (`config.yml`, `overrides.yml`,
`consoles.yml`) goes through the module-level ``_yaml_rt`` round-trip loader so
that comments and formatting survive a load/save cycle.

Line-ending policy: ``save_config`` and ``save_overrides`` always emit LF
(``newline="\n"``) regardless of the source file's original line endings. Users
whose ``config.yml`` was originally CRLF (Windows default) will see it become
LF after the first TUI save. This matches ruamel.yaml's native output and
modern editor conventions; preserving the source's CRLF would require an extra
detection step that this project deliberately avoids.
"""

from __future__ import annotations

import io
import os
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError
from ruamel.yaml import YAML, YAMLError

_yaml_rt = YAML(typ="rt")
_yaml_rt.preserve_quotes = True
_yaml_rt.indent(mapping=2, sequence=4, offset=2)


class ConfigError(Exception):
    """Raised when user-facing config fails to load or validate."""


class Config(BaseModel):
    roms_root: Path
    bios_root: Path = Path("BIOS")
    cache_dir: Path = Path(".cache")
    log_file: Path = Path("retrofetch.log")
    default_limit: int = 75
    dry_run: bool = False
    region_priority: list[str] = Field(
        default_factory=lambda: ["USA", "World", "Europe", "Japan"]
    )
    exclude_keywords: list[str] = Field(
        default_factory=lambda: [
            "(Beta)",
            "(Proto)",
            "(Demo)",
            "(Sample)",
            "(Kiosk)",
            "(Trade Demo)",
        ]
    )
    max_game_size_gb: float | None = None
    max_concurrent_downloads: int = 3
    extract_archives: bool = False
    source_fallback_by_class: dict[str, list[str]] = Field(
        default_factory=lambda: {
            "A": ["minerva_http", "archive_org", "romsfun", "romsretro"],
            "B": ["minerva_http", "archive_org", "romsretro"],
            "C": ["minerva_http", "archive_org", "romsfun", "romsretro"],
        }
    )
    ranking_sources_by_class: dict[str, list[str]] = Field(
        default_factory=lambda: {
            "A": ["minerva_http", "archive_org", "romsfun", "romsretro", "vimm", "coolrom"],
            "B": ["minerva_http", "archive_org", "romsretro", "vimm", "coolrom"],
            "C": ["minerva_http", "archive_org", "romsfun", "romsretro", "vimm"],
        }
    )


class ConsoleOverride(BaseModel):
    include: list[str] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)
    limit: int | None = None
    region_priority: list[str] | None = None


def load_config(path: Path = Path("config.yml")) -> Config:
    if not path.exists():
        raise ConfigError(
            f"Config file not found: {path}. Run 'retrofetch init' to create a default."
        )
    try:
        raw = _yaml_rt.load(path.read_text(encoding="utf-8"))
    except YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        loc = f"{mark.line + 1}:{mark.column + 1}" if mark else "?"
        problem = getattr(exc, "problem", str(exc))
        raise ConfigError(f"Invalid YAML in {path}:{loc}: {problem}") from exc
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ConfigError(
            f"Config in {path} must be a mapping, got {type(raw).__name__}"
        )
    try:
        return Config(**raw)
    except ValidationError as exc:
        errors = "; ".join(
            f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}" for e in exc.errors()
        )
        raise ConfigError(f"Config validation failed in {path}: {errors}") from exc


def load_overrides(path: Path = Path("overrides.yml")) -> dict[str, ConsoleOverride]:
    if not path.exists():
        return {}
    try:
        raw = _yaml_rt.load(path.read_text(encoding="utf-8"))
    except YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        loc = f"{mark.line + 1}:{mark.column + 1}" if mark else "?"
        problem = getattr(exc, "problem", str(exc))
        raise ConfigError(f"Invalid YAML in {path}:{loc}: {problem}") from exc
    if raw is None:
        return {}
    consoles = raw.get("consoles", {}) if isinstance(raw, dict) else {}
    if not isinstance(consoles, dict):
        raise ConfigError(f"overrides.consoles in {path} must be a mapping")
    result: dict[str, ConsoleOverride] = {}
    for shortname, override_data in consoles.items():
        if override_data is None:
            override_data = {}
        try:
            result[shortname] = ConsoleOverride(**override_data)
        except ValidationError as exc:
            errors = "; ".join(
                f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}"
                for e in exc.errors()
            )
            raise ConfigError(
                f"Override validation failed for console '{shortname}' in {path}: {errors}"
            ) from exc
    return result


def _atomic_dump(path: Path, data) -> None:
    buf = io.StringIO()
    _yaml_rt.dump(data, buf)
    text = buf.getvalue()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def save_config(path: Path, data) -> None:
    """Atomic LF-normalized save of a loaded round-trip object.

    ``data`` should be a ruamel.yaml ``CommentedMap`` (or equivalent
    round-trippable structure) previously obtained via ``_yaml_rt.load``.
    Writes are atomic: stage to ``<path>.tmp``, ``fsync``, then ``os.replace``.
    """
    _atomic_dump(path, data)


def save_overrides(path: Path, data) -> None:
    """Atomic LF-normalized save of a loaded round-trip object.

    ``data`` should be a ruamel.yaml ``CommentedMap`` (or equivalent
    round-trippable structure) previously obtained via ``_yaml_rt.load``.
    Writes are atomic: stage to ``<path>.tmp``, ``fsync``, then ``os.replace``.
    """
    _atomic_dump(path, data)
