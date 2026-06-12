from __future__ import annotations

from pathlib import Path

from retrofetch.config import Config, load_config


def test_extract_archives_defaults_false() -> None:
    config = Config(roms_root=Path("ROMs"))

    assert config.extract_archives is False
    assert config.bios_root == Path("BIOS")


def test_extract_archives_can_be_enabled(scratch_path) -> None:
    config_file = scratch_path / "config.yml"
    config_file.write_text(
        "\n".join(
            [
                'roms_root: "ROMs"',
                "extract_archives: true",
            ]
        ),
        encoding="utf-8",
    )

    assert load_config(config_file).extract_archives is True


def test_example_config_documents_keep_archive_default() -> None:
    text = Path("config.yml.example").read_text(encoding="utf-8")

    assert "extract_archives: false" in text
    assert "bios_root:" in text
