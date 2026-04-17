"""YAML config loader and schema validation."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, ValidationError


class ConfigError(Exception):
    """Raised when user-facing config fails to load or validate."""


class Config(BaseModel):
    roms_root: Path
    cache_dir: Path = Path(".cache")
    log_file: Path = Path("retrofetch.log")
    default_limit: int = 75
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
    source_fallback_by_class: dict[str, list[str]] = Field(
        default_factory=lambda: {
            "A": ["archive_org", "minerva_http", "minerva_torrent", "romsfun"],
            "B": ["minerva_torrent", "minerva_http", "archive_org", "romsretro"],
            "C": ["romsfun", "romsretro", "archive_org"],
        }
    )
    ranking_sources_by_class: dict[str, list[str]] = Field(
        default_factory=lambda: {
            "A": ["romsfun", "romsretro", "archive_org"],
            "B": ["archive_org", "romsretro"],
            "C": ["romsfun", "romsretro"],
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
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
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
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
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
