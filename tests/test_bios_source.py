from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path

import pytest
from typer.testing import CliRunner

from retrofetch.config import Config
from retrofetch.sources.bios import BiosFile, BiosSource
from retrofetch.sources import SourceUnavailable


def test_config_has_bios_root_default() -> None:
    assert Config(roms_root=Path("ROMs")).bios_root.name == "BIOS"


def test_bios_list_prefers_minerva_and_sorts_by_size(monkeypatch) -> None:
    source = BiosSource()
    monkeypatch.setattr(
        source,
        "_minerva_files",
        lambda console: [
            BiosFile(console, "large.bin", "https://m/large.bin", 100, "minerva_http"),
            BiosFile(console, "small.bin", "https://m/small.bin", 10, "minerva_http"),
        ],
    )
    monkeypatch.setattr(
        source,
        "_archive_files",
        lambda console: [
            BiosFile(console, "fallback.bin", "https://a/fallback.bin", 1, "archive_org")
        ],
    )

    catalog = source.list_files("psx")

    assert [file.filename for file in catalog.files] == ["small.bin", "large.bin"]
    assert {file.source for file in catalog.files} == {"minerva_http"}


def test_bios_list_uses_archive_fallback(monkeypatch) -> None:
    source = BiosSource()
    monkeypatch.setattr(source, "_minerva_files", lambda console: [])
    monkeypatch.setattr(
        source,
        "_archive_files",
        lambda console: [
            BiosFile(console, "scph5501.bin", "https://a/scph5501.bin", 512, "archive_org")
        ],
    )

    catalog = source.list_files("psx")

    assert catalog.console == "psx"
    assert catalog.files[0].source == "archive_org"


def test_bios_download_skips_existing_and_streams_missing(
    monkeypatch, scratch_path
) -> None:
    source = BiosSource()
    monkeypatch.setattr(
        source,
        "list_files",
        lambda console: SimpleNamespace(
            console=console,
            files=[
                BiosFile(console, "exists.bin", "https://m/exists.bin", 10, "minerva_http"),
                BiosFile(console, "new.bin", "https://m/new.bin", 20, "minerva_http"),
            ],
        ),
    )
    target = scratch_path / "psx"
    target.mkdir()
    (target / "exists.bin").write_bytes(b"already")
    streamed = []

    def fake_stream(url, final, **kwargs):
        streamed.append((url, final, kwargs))
        final.write_bytes(b"new")
        return SimpleNamespace(path=final)

    monkeypatch.setattr("retrofetch.sources.bios.stream_http_download", fake_stream)

    paths = source.download("psx", scratch_path)

    assert paths == [target / "exists.bin", target / "new.bin"]
    assert len(streamed) == 1
    assert streamed[0][0] == "https://m/new.bin"


def test_bios_unsupported_console_errors() -> None:
    with pytest.raises(SourceUnavailable):
        BiosSource().list_files("nes")


def test_cli_bios_command_downloads_to_configured_root(monkeypatch, scratch_path) -> None:
    from retrofetch import cli as cli_mod

    config_path = scratch_path / "config.yml"
    bios_root = scratch_path / "BIOS"
    config_path.write_text(
        "\n".join(
            [
                f'roms_root: "{(scratch_path / "ROMs").as_posix()}"',
                f'bios_root: "{bios_root.as_posix()}"',
            ]
        ),
        encoding="utf-8",
    )

    class _FakeBiosSource:
        def list_files(self, console: str):
            return SimpleNamespace(
                console=console,
                files=[
                    BiosFile(console, "scph5501.bin", "https://example/scph5501.bin", 10, "archive_org")
                ],
            )

        def download(self, console: str, root: Path, *, limit: int | None = None):
            target = root / console
            target.mkdir(parents=True, exist_ok=True)
            path = target / "scph5501.bin"
            path.write_bytes(b"bios")
            return [path]

    monkeypatch.setattr(cli_mod, "BiosSource", _FakeBiosSource)
    result = CliRunner().invoke(
        cli_mod.app,
        ["bios", "--console", "psx", "--config", str(config_path)],
    )

    assert result.exit_code == 0, result.output
    assert (bios_root / "psx" / "scph5501.bin").read_bytes() == b"bios"
