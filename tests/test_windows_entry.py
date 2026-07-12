from __future__ import annotations

import os

from retrofetch.config import user_config_path
from retrofetch.windows_entry import executable_argv


def test_standalone_exe_opens_tui_with_per_user_config(
    monkeypatch, scratch_path
) -> None:
    if os.name == "nt":
        monkeypatch.setenv("LOCALAPPDATA", str(scratch_path))
        expected = scratch_path / "Retrofetch" / "config.yml"
    else:
        monkeypatch.setenv("XDG_CONFIG_HOME", str(scratch_path))
        expected = scratch_path / "retrofetch" / "config.yml"

    assert user_config_path() == expected
    assert executable_argv(["Retrofetch.exe"]) == [
        "Retrofetch.exe",
        "tui",
        "--config",
        str(expected),
    ]


def test_standalone_exe_preserves_explicit_cli_arguments() -> None:
    assert executable_argv(["Retrofetch.exe", "--version"]) == [
        "Retrofetch.exe",
        "--version",
    ]
