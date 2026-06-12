from __future__ import annotations

import pytest

from retrofetch.organizer import place_file, safe_target_path
from retrofetch.sanitize import sanitize_filename


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Game: Special.zip", "Game - Special.zip"),
        ("Game <Special>.zip", "Game -Special-.zip"),
        ("Game? Name*.zip", "Game- Name-.zip"),
        ("Game/Name\\Part.zip", "Game-Name-Part.zip"),
        ("Game. .zip", "Game.zip"),
        ("CON.zip", "CON_.zip"),
        ("LPT1.bin", "LPT1_.bin"),
        ("Legend of Zelda, The (USA).zip", "Legend of Zelda, The (USA).zip"),
    ],
)
def test_sanitize_filename_windows_cases(raw: str, expected: str) -> None:
    assert sanitize_filename(raw) == expected


def test_safe_target_path_truncates_to_windows_guard(scratch_path) -> None:
    long_title = "A" * 300 + " (USA).zip"

    target = safe_target_path(scratch_path, long_title)

    assert len(str(target.resolve())) <= 240
    assert target.name.endswith("(USA).zip")


def test_hostile_filename_can_be_written_to_disk(scratch_path) -> None:
    target = safe_target_path(scratch_path, "Game: <Special?> Edition (USA).zip")

    target.write_bytes(b"x")

    assert target.exists()
    assert not any(char in target.name for char in '<>:"/\\|?*')


def test_place_file_uses_sanitized_target(scratch_path) -> None:
    extracted = scratch_path / "incoming.bin"
    extracted.write_bytes(b"payload")

    result = place_file(extracted, scratch_path / "out", "AUX: Game?.bin")

    assert result.status == "placed"
    assert result.final_path.name == "AUX - Game-.bin"
    assert result.final_path.read_bytes() == b"payload"
