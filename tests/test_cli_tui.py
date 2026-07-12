from __future__ import annotations

import sys

import pytest
import typer

from retrofetch import cli as cli_mod
from retrofetch.tui import app as app_mod


def test_tui_custom_config_path_drives_first_run(monkeypatch, scratch_path) -> None:
    captured = {}

    class _FakeApp:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

        def run(self) -> int:
            return 0

    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.delenv("MSYSTEM", raising=False)
    monkeypatch.delenv("PSEDIT", raising=False)
    monkeypatch.setattr(app_mod, "RetrofetchApp", _FakeApp)
    config_path = scratch_path / "profile" / "config.yml"

    with pytest.raises(typer.Exit) as exc_info:
        cli_mod.tui(config_path=config_path)

    resolved = config_path.resolve()
    assert exc_info.value.exit_code == 0
    assert captured["config_path"] == resolved
    assert captured["overrides_path"] == resolved.with_name("overrides.yml")
    assert captured["first_run"] is True
    assert captured["config"].cache_dir == resolved.parent / "cache"
    assert captured["config"].log_file == resolved.parent / "retrofetch.log"


def test_tui_does_not_overwrite_invalid_existing_config(
    monkeypatch, scratch_path
) -> None:
    config_path = scratch_path / "profile" / "config.yml"
    config_path.parent.mkdir(parents=True)
    invalid = "roms_root: [broken\n"
    config_path.write_text(invalid, encoding="utf-8")
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.delenv("MSYSTEM", raising=False)
    monkeypatch.delenv("PSEDIT", raising=False)

    with pytest.raises(typer.Exit) as exc_info:
        cli_mod.tui(config_path=config_path)

    assert exc_info.value.exit_code == 2
    assert config_path.read_text(encoding="utf-8") == invalid
