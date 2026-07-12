from __future__ import annotations

from retrofetch.config import user_config_path
from retrofetch.windows_entry import executable_argv


def test_standalone_exe_opens_tui_with_per_user_config(
    monkeypatch, scratch_path
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(scratch_path))

    assert user_config_path() == scratch_path / "Retrofetch" / "config.yml"
    assert executable_argv(["Retrofetch.exe"]) == [
        "Retrofetch.exe",
        "tui",
        "--config",
        str(scratch_path / "Retrofetch" / "config.yml"),
    ]


def test_standalone_exe_preserves_explicit_cli_arguments() -> None:
    assert executable_argv(["Retrofetch.exe", "--version"]) == [
        "Retrofetch.exe",
        "--version",
    ]
