from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from retrofetch.library_audit import audit_library, collect_library_files


def put(root: Path, name: str, content: str = "fixture") -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_hidden_assets_housekeeping_and_directory_as_file(tmp_path: Path):
    playlist = put(tmp_path, "psx/Game.m3u/Game.m3u", "\ufeff# comment\n../.hidden/disc.cue\n")
    cue = put(tmp_path, "psx/.hidden/disc.cue", 'FILE "../.discs/Track 1.bin" BINARY\nTRACK 01 MODE2/2352\n')
    track = put(tmp_path, "psx/.discs/Track 1.bin")
    for name in (".retrofetch-state.json", ".retrofetch-staging/a.part", ".retrofetch-job/tmp",
                 ".multidisc-staging/a", ".addons/a", ".git/config", "__pycache__/a",
                 "psx/info.json", "psx/manifest.install", "psx/systeminfo.txt",
                 "psx/gamelist.xml", "psx/site.url", "psx/link.desktop"):
        put(tmp_path, name)
    assert collect_library_files(tmp_path) == sorted([playlist, cue, track])
    before = {p: p.read_bytes() for p in (playlist, cue, track)}
    report = audit_library(tmp_path)
    assert report["issues"] == []
    assert report["total_bytes"] == sum(map(len, before.values()))
    assert json.loads(json.dumps(report))["file_count"] == 3
    assert before == {p: p.read_bytes() for p in before}


def test_missing_case_sensitive_and_unsafe_references(tmp_path: Path):
    put(tmp_path, "psx/Disc.bin")
    put(tmp_path, "psx/game.m3u", "disc.bin\nmissing.bin\n../../escape.bin\nC:/Disc.bin\nhttps://x/a\n/absolute.bin\n")
    put(tmp_path, "psx/broken.cue", 'FILE "unterminated BINARY\n')
    put(tmp_path, "psx/bare.cue", 'FILE Disc.bin BINARY\n')
    issues = audit_library(tmp_path)["issues"]
    assert sum(i["code"] == "missing_reference" for i in issues) == 2
    assert sum(i["code"] == "unsafe_reference" for i in issues) == 4
    assert any(i["code"] == "malformed_playlist" and i["path"].endswith("broken.cue") for i in issues)
    assert not any(i["path"].endswith("bare.cue") for i in issues)


def test_collector_rejects_symlinks_including_root_ancestor(tmp_path: Path):
    real = tmp_path / "real"
    put(real, "roms/game.chd")
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)
    with pytest.raises(ValueError, match="Symlink"):
        collect_library_files(alias / "roms")
    (real / "roms/link.chd").symlink_to(real / "roms/game.chd")
    with pytest.raises(ValueError, match="symlinks"):
        collect_library_files(real)
    assert audit_library(real)["error_count"] == 1


@pytest.mark.parametrize("names", [("Game.chd", "game.chd"), ("bad\\name.chd",), ("bad\x01.chd",)])
def test_collector_rejects_android_unsafe_names(tmp_path: Path, names: tuple[str, ...]):
    for name in names:
        put(tmp_path, name)
    with pytest.raises(ValueError):
        collect_library_files(tmp_path)


def test_collector_rejects_nonregular_and_missing_root(tmp_path: Path):
    with pytest.raises(ValueError):
        collect_library_files(tmp_path / "missing")
    if not hasattr(os, "mkfifo"):
        pytest.skip("FIFO requires POSIX")
    os.mkfifo(tmp_path / "pipe")
    with pytest.raises(ValueError, match="regular"):
        collect_library_files(tmp_path)


def test_multidisc_candidates_keep_regions_revisions_and_disc_identity(tmp_path: Path):
    for name in ("Game (USA) (Disc 1).rvz", "Game (USA) (Disc 2).rvz",
                 "Game (Europe) (Disc 1).rvz", "Game (USA) (Rev 1) (Disc 1).rvz"):
        put(tmp_path, "gc/" + name)
    report = audit_library(tmp_path)
    assert report["error_count"] == 0  # No assumption that GameCube supports M3U.
    assert [i["code"] for i in report["issues"]] == ["multidisc_review"]
    put(tmp_path, "gc/Game (USA) (Disc 1).iso")
    report = audit_library(tmp_path)
    assert [i["code"] for i in report["issues"]].count("duplicate_candidate") == 1
    put(tmp_path, "gc/Game (USA).m3u", "Game (USA) (Disc 1).rvz\nGame (USA) (Disc 2).rvz\nGame (USA) (Disc 1).iso\n")
    assert audit_library(tmp_path)["issues"] == []


def test_readiness_errors_and_preparation_warnings(tmp_path: Path):
    put(tmp_path, "empty.chd", "")
    put(tmp_path, "download.part")
    put(tmp_path, "source.zip")
    put(tmp_path, "switch/Game/Game.nro")
    malformed = put(tmp_path, "invalid.m3u")
    malformed.write_bytes(b"\xff\xfe\xff")
    issues = {i["code"]: i["severity"] for i in audit_library(tmp_path)["issues"]}
    assert issues == {"empty_file": "error", "partial_download": "error",
                      "source_archive": "warning", "nested_nro": "warning",
                      "unreadable_playlist": "error"}


def test_playlist_cycles_and_shared_acyclic_dependencies(tmp_path: Path):
    put(tmp_path, "a.m3u", "b.m3u\nc.m3u\n")
    put(tmp_path, "b.m3u", "c.m3u\n")
    put(tmp_path, "c.m3u", "disc.chd\n")
    put(tmp_path, "disc.chd")
    assert audit_library(tmp_path)["issues"] == []
    put(tmp_path, "c.m3u", "a.m3u\n")
    report = audit_library(tmp_path)
    assert report["error_count"] >= 1
    assert all(i["code"] == "cyclic_playlist" for i in report["issues"])
    put(tmp_path, "c.m3u", "c.m3u\n")
    assert audit_library(tmp_path)["issues"][0]["code"] == "cyclic_playlist"


def test_dotdot_requires_real_directory_traversal(tmp_path: Path):
    put(tmp_path, "disc.chd")
    put(tmp_path, "file")
    (tmp_path / "directory").mkdir()
    put(tmp_path, "game.m3u", "missing/../disc.chd\nfile/../disc.chd\ndirectory/../disc.chd\n")
    report = audit_library(tmp_path)
    assert report["error_count"] == 2
    assert [i["code"] for i in report["issues"]] == ["missing_reference", "missing_reference"]
