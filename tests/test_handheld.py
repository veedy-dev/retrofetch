from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path, PurePosixPath

import pytest
from typer.testing import CliRunner

from retrofetch import handheld


class LocalADB(handheld.ADB):
    """Execute the real quoted shell scripts against a disposable device tree."""

    def __init__(self, root: Path):
        self.serial = "fixture-device"
        self.root = root
        (root / "CARD").mkdir(parents=True)
        self.free = 100 * 1024 ** 3
        self.push_count = 0
        self.failure = ""

    def local(self, path: PurePosixPath) -> Path:
        return self.root / path.relative_to("/storage")

    def shell(self, script: str, *, timeout: int = 60) -> str:
        script = script.replace("/storage", str(self.root))
        result = subprocess.run(["sh", "-c", script], capture_output=True, text=True, check=False, timeout=timeout)
        if result.returncode:
            raise handheld.HandheldError(result.stderr)
        return result.stdout.replace(str(self.root), "/storage")

    def children(self, path: PurePosixPath) -> list[str]:
        if path == PurePosixPath("/"):
            return ["storage"]
        return super().children(path)

    def space(self, volume: PurePosixPath) -> dict:
        return {"path": str(volume), "total_bytes": 100 * 1024 ** 3, "free_bytes": self.free}

    def push(self, source: Path, destination: PurePosixPath) -> None:
        self.push_count += 1
        target = self.local(destination)
        if self.failure == "interrupt":
            target.write_bytes(b"partial")
            raise handheld.HandheldError("push timed out")
        shutil.copyfile(source, target)
        if self.failure == "corrupt":
            target.write_bytes(b"wrong")
        if self.failure == "race":
            (target.parent / source.name).write_bytes(b"new owner")


@pytest.fixture
def library(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "game.rom").write_bytes(b"known payload")
    return source, LocalADB(tmp_path / "device")


def run_transfer(library, *, apply=False, reserve=0):
    source, adb = library
    return handheld.transfer_library(source, "/storage/CARD/ROMs", adb, reserve, apply)


def test_dry_run_hidden_assets_and_rerun(library):
    source, adb = library
    hidden = source / ".discs"
    hidden.mkdir()
    (hidden / "disc.bin").write_bytes(b"disc bytes")
    before = sorted(adb.root.rglob("*"))
    report = run_transfer(library)
    assert report["status"] == "planned"
    assert {item["path"] for item in report["files"]} == {"game.rom", ".discs/disc.bin"}
    assert sorted(adb.root.rglob("*")) == before
    assert adb.push_count == 0
    applied = run_transfer(library, apply=True)
    assert applied["status"] == "complete"
    assert (adb.root / "CARD/ROMs/.discs/disc.bin").read_bytes() == b"disc bytes"
    assert (source / "game.rom").read_bytes() == b"known payload"
    again = run_transfer(library, apply=True)
    assert {item["action"] for item in again["files"]} == {"skip"}
    assert adb.push_count == 2


def test_same_size_conflict_and_capacity_never_mutate(library):
    _, adb = library
    destination = adb.root / "CARD/ROMs"
    destination.mkdir()
    existing = destination / "game.rom"
    existing.write_bytes(b"other payload")
    report = run_transfer(library, apply=True)
    assert report["status"] == "blocked"
    assert report["files"][0]["action"] == "conflict"
    assert existing.read_bytes() == b"other payload"
    existing.unlink()
    adb.free = 5 * 1024 ** 3
    report = run_transfer(library, apply=True, reserve=5)
    assert report["capacity_ok"] is False
    assert list(destination.iterdir()) == []
    assert adb.push_count == 0


@pytest.mark.parametrize("failure", ["corrupt", "interrupt", "race"])
def test_failed_push_never_publishes_and_cleans_only_owned_temp(library, failure):
    source, adb = library
    destination = adb.root / "CARD/ROMs"
    destination.mkdir()
    unowned = destination / ".retrofetch-unowned"
    unowned.write_bytes(b"leave alone")
    adb.failure = failure
    with pytest.raises(handheld.HandheldError):
        run_transfer(library, apply=True)
    final = destination / "game.rom"
    if failure == "race":
        assert final.read_bytes() == b"new owner"
    else:
        assert not final.exists()
    assert list(destination.glob(".retrofetch-*")) == [unowned]
    assert (source / "game.rom").read_bytes() == b"known payload"


def test_remote_symlink_and_case_alias_fail_closed(library):
    source, adb = library
    destination = adb.root / "CARD/ROMs"
    destination.symlink_to(source, target_is_directory=True)
    with pytest.raises(handheld.HandheldError, match="link"):
        run_transfer(library, apply=True)
    destination.unlink()
    destination.mkdir()
    (destination / "GAME.rom").write_bytes(b"old")
    with pytest.raises(handheld.HandheldError, match="Case collision"):
        run_transfer(library, apply=True)
    assert (destination / "GAME.rom").read_bytes() == b"old"
    assert adb.push_count == 0


def test_quoted_shell_names_and_path_escape(library):
    source, adb = library
    name = "a'$(touch HACKED); title.rom"
    (source / name).write_bytes(b"safe")
    run_transfer(library, apply=True)
    assert (adb.root / "CARD/ROMs" / name).read_bytes() == b"safe"
    for destination in ["/storage/CARD/ROMs/../Android/data", "/data/ROMs", "/storage/CARD/ROMs//a", "/storage/CARD/ROMs/Android/data", "/storage/CARD/ROMs/a\nxx"]:
        with pytest.raises(handheld.HandheldError):
            handheld.transfer_library(source, destination, adb, 0, True)
    assert not Path("HACKED").exists()


def test_cli_exit_codes_and_explicit_device(library, monkeypatch):
    source, adb = library
    monkeypatch.setattr(handheld, "ADB", lambda serial: adb)
    runner = CliRunner()
    missing = runner.invoke(handheld.app, ["transfer", str(source), "--destination", "/storage/CARD/ROMs"])
    assert missing.exit_code == 2
    result = runner.invoke(handheld.app, ["transfer", str(source), "--destination", "/storage/CARD/ROMs", "--serial", "fixture-device", "--headroom-gib", "nan"])
    assert result.exit_code == 2
    assert "finite" in json.loads(result.stdout)["error"]
    adb.free = 0
    blocked = runner.invoke(handheld.app, ["transfer", str(source), "--destination", "/storage/CARD/ROMs", "--serial", "fixture-device"])
    assert blocked.exit_code == 1
    assert json.loads(blocked.stdout)["status"] == "blocked"
    for command in ("inspect", "transfer", "audit"):
        assert runner.invoke(handheld.app, [command, "--help"]).exit_code == 0


def test_adb_rejects_unavailable_unauthorized_and_ambiguous(monkeypatch):
    for devices in ("SERIAL offline", "SERIAL unauthorized", "SERIAL device\nSERIAL device", "OTHER device"):
        monkeypatch.setattr(handheld.ADB, "run", lambda self, *args, rows=devices: "List of devices attached\n" + rows)
        with pytest.raises(handheld.HandheldError, match="authorized"):
            handheld.ADB("SERIAL")


def test_space_is_rechecked_before_push(library, monkeypatch):
    _, adb = library
    original = adb.space
    calls = 0

    def shrinking(volume):
        nonlocal calls
        calls += 1
        if calls > 1:
            adb.free = 0
        return original(volume)

    monkeypatch.setattr(adb, "space", shrinking)
    with pytest.raises(handheld.HandheldError, match="space changed"):
        run_transfer(library, apply=True)
    assert adb.push_count == 0
    assert not (adb.root / "CARD/ROMs").exists()


def test_publication_does_not_clobber_a_late_target(library, monkeypatch):
    _, adb = library
    original = adb.command

    def racing_command(*args):
        if args[0] == "mv":
            adb.local(PurePosixPath(args[-1])).write_bytes(b"late owner")
        return original(*args)

    monkeypatch.setattr(adb, "command", racing_command)
    with pytest.raises(handheld.HandheldError, match="No-clobber"):
        run_transfer(library, apply=True)
    assert (adb.root / "CARD/ROMs/game.rom").read_bytes() == b"late owner"
    assert not list((adb.root / "CARD/ROMs").glob(".retrofetch-*"))


def test_source_parent_segments_are_normalized_after_validation(library):
    source, adb = library
    other = source.parent / "other"
    other.mkdir()
    report = handheld.transfer_library(other / ".." / source.name, "/storage/CARD/ROMs", adb, 0, True)
    assert report["status"] == "complete"
    assert (adb.root / "CARD/ROMs/game.rom").read_bytes() == b"known payload"


def test_allocation_rounding_and_directories_preserve_reserve(library, monkeypatch):
    source, adb = library
    (source / "game.rom").write_bytes(b"x")
    unit, reserve = 256 * 1024, 5 * 1024 ** 3
    command, push = adb.command, adb.push

    def allocating_command(*args):
        if args[:4] == ("stat", "-f", "-c", "%S"):
            return str(unit)
        if args[0] == "mkdir":
            adb.free -= 2 * unit
        return command(*args)

    def allocating_push(local, remote):
        adb.free -= ((local.stat().st_size + unit - 1) // unit + 2) * unit
        push(local, remote)

    monkeypatch.setattr(adb, "command", allocating_command)
    monkeypatch.setattr(adb, "push", allocating_push)
    # Logical bytes fit; allocation alone cannot fit. No directories may be created.
    adb.free = reserve + 1024
    assert run_transfer(library, apply=True, reserve=5)["status"] == "blocked"
    assert not (adb.root / "CARD/ROMs").exists()
    # Payload allocation fits, but directory creation must also be budgeted.
    adb.free = reserve + 3 * unit
    assert run_transfer(library, apply=True, reserve=5)["status"] == "blocked"
    assert not (adb.root / "CARD/ROMs").exists()
    adb.free = reserve + 5 * unit
    assert run_transfer(library, apply=True, reserve=5)["status"] == "complete"
    assert adb.free == reserve
    assert (adb.root / "CARD/ROMs/game.rom").read_bytes() == b"x"
