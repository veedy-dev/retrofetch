from __future__ import annotations

from pathlib import Path

from retrofetch.config import Config, load_config


def test_extract_archives_defaults_false() -> None:
    config = Config(roms_root=Path("ROMs"))

    assert config.extract_archives is False
    assert config.bios_root == Path("BIOS")


def test_minerva_catalog_and_torrent_are_enabled_by_default() -> None:
    config = Config(roms_root=Path("ROMs"))

    for klass in ("A", "B", "C"):
        assert config.ranking_sources_by_class[klass][0] == "minerva_http"
        assert "minerva_http" not in config.source_fallback_by_class[klass]
        assert config.source_fallback_by_class[klass][0] == "minerva_torrent"
    assert config.torrent_mode == "managed"


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
