"""Explicit-device, additive ROM transfers. No configuration or package mutations."""
from __future__ import annotations

import hashlib
import json
import math
import re
import shlex
import subprocess
from pathlib import Path, PurePosixPath

import typer

from .library_audit import audit_library, collect_library_files

app = typer.Typer(help="Inspect Android handhelds, audit libraries, and safely add ROMs.")


class HandheldError(ValueError):
    """An unsafe input or failed ADB operation."""


def _emit(value: dict) -> None:
    typer.echo(json.dumps(value, ensure_ascii=True, indent=2))


def _safe_name(value: str) -> None:
    if not value or "\\" in value or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise HandheldError(f"Unsafe path or serial: {value!r}")


def _destination(value: str) -> PurePosixPath:
    _safe_name(value)
    parts = value.split("/")
    if (len(parts) < 4 or parts[:2] != ["", "storage"]
            or any(p in {"", ".", ".."} for p in parts[1:])):
        raise HandheldError("Destination must be /storage/VOLUME/ROMs[/subdir], without traversal.")
    roms = 4 if parts[2:4] == ["emulated", "0"] else 3
    if len(parts) <= roms or parts[roms] != "ROMs" or not re.fullmatch(r"[A-Za-z0-9_-]+", parts[2]):
        raise HandheldError("Destination must be inside a shared /storage/VOLUME/ROMs tree.")
    if any(p.casefold() == "android" for p in parts[roms + 1:]):
        raise HandheldError("Android configuration/data paths are not transfer destinations.")
    return PurePosixPath(value)


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class ADB:
    """The only device boundary; remote shell arguments are always quoted."""

    def __init__(self, serial: str):
        _safe_name(serial)
        if serial.startswith("-") or any(c.isspace() for c in serial):
            raise HandheldError("Supply one explicit ADB serial (see adb devices).")
        self.serial = serial
        rows = [line.split() for line in self.run("devices").splitlines()[1:] if line.strip()]
        matches = [row for row in rows if row[0] == serial]
        if len(matches) != 1 or len(matches[0]) < 2 or matches[0][1] != "device":
            raise HandheldError(f"Device {serial!r} must appear exactly once as authorized 'device' in adb devices.")
        self.shell("for c in stat sha256sum df getprop wm pm mktemp mkdir mv rm; do command -v \"$c\" >/dev/null || exit 1; done")

    def run(self, *args: str, timeout: int = 60) -> str:
        try:
            result = subprocess.run(["adb", *args], capture_output=True, text=True,
                                    check=True, timeout=timeout)
        except (OSError, subprocess.SubprocessError) as exc:
            detail = getattr(exc, "stderr", None) or str(exc)
            raise HandheldError(f"ADB failed; check device authorization, connection and commands: {detail}") from exc
        return result.stdout

    def shell(self, script: str, *, timeout: int = 60) -> str:
        return self.run("-s", self.serial, "shell", script, timeout=timeout)

    def command(self, *args: str) -> str:
        return self.shell(shlex.join(args), timeout=3600 if args[0] == "sha256sum" else 60)

    def kind(self, path: PurePosixPath) -> str:
        q = shlex.quote(str(path))
        return self.shell(f"if [ -L {q} ]; then echo link; elif [ -d {q} ]; then echo dir; "
                          f"elif [ -f {q} ]; then echo file; elif [ -e {q} ]; then echo other; "
                          "else echo missing; fi").strip()

    def children(self, path: PurePosixPath) -> list[str]:
        q = shlex.quote(str(path))
        output = self.shell(f"[ -r {q} ] && [ -x {q} ] || exit 1; "
                            f"for p in {q}/* {q}/.[!.]* {q}/..?*; do "
                            '[ -e "$p" ] || [ -L "$p" ] || continue; printf \'%s\\0\' "${p##*/}"; done')
        return [name for name in output.split("\0") if name]

    def check_path(self, path: PurePosixPath, *, directory: bool = False) -> str:
        """Reject links, non-directories and case aliases at every existing ancestor."""
        parent = PurePosixPath("/")
        for part in path.parts[1:]:
            _safe_name(part)
            names = self.children(parent)
            if any(name != part and name.casefold() == part.casefold() for name in names):
                raise HandheldError(f"Case collision at {parent / part}")
            parent /= part
            kind = self.kind(parent)
            if kind == "missing":
                return kind
            expected = "dir" if parent != path or directory else "file"
            if kind != expected:
                raise HandheldError(f"Unsafe remote path {parent}: expected {expected}, found {kind}")
        return "dir" if directory else "file"

    def fingerprint(self, path: PurePosixPath) -> tuple[int, str]:
        try:
            size = int(self.command("stat", "-c", "%s", str(path)).strip())
            digest = self.command("sha256sum", str(path)).split()[0]
        except (ValueError, IndexError) as exc:
            raise HandheldError(f"Cannot read device size/hash: {path}") from exc
        if size < 0 or not re.fullmatch(r"[a-fA-F0-9]{64}", digest):
            raise HandheldError(f"Invalid size/hash from device: {path}")
        return size, digest.lower()

    def space(self, volume: PurePosixPath) -> dict:
        lines = self.command("df", "-k", str(volume)).splitlines()
        try:
            fields = lines[-1].split()
            total, free = int(fields[-5]) * 1024, int(fields[-3]) * 1024
            if total <= 0 or not 0 <= free <= total:
                raise ValueError
        except (ValueError, IndexError) as exc:
            raise HandheldError(f"Cannot parse device free space for {volume}") from exc
        return {"path": str(volume), "total_bytes": total, "free_bytes": free}

    def push(self, source: Path, destination: PurePosixPath) -> None:
        self.run("-s", self.serial, "push", str(source), str(destination), timeout=3600)


def _volume(destination: PurePosixPath) -> PurePosixPath:
    return PurePosixPath(*destination.parts[:4 if destination.parts[2] == "emulated" else 3])


def transfer_library(source: Path, destination: str, adb: ADB, headroom_gib: float,
                     apply: bool = False) -> dict:
    """Preflight the whole tree before making any device changes."""
    if not math.isfinite(headroom_gib) or headroom_gib < 0:
        raise HandheldError("--headroom-gib must be finite and nonnegative.")
    target = _destination(destination)
    volume = _volume(target)
    if adb.check_path(volume, directory=True) != "dir":
        raise HandheldError(f"Shared volume is not mounted: {volume}")
    adb.check_path(target, directory=True)
    files = collect_library_files(source)
    root = source.resolve(strict=True)
    numerator, denominator = headroom_gib.as_integer_ratio()
    reserve = (numerator * 1024 ** 3 + denominator - 1) // denominator
    entries = []
    for path in files:
        relative = path.relative_to(root).as_posix()
        remote = target / relative
        size, digest = path.stat().st_size, _digest(path)
        kind = adb.check_path(remote)
        action = "copy" if kind == "missing" else (
            "skip" if adb.fingerprint(remote) == (size, digest) else "conflict")
        entries.append({"path": relative, "size_bytes": size, "sha256": digest, "action": action})
    capacity = adb.space(volume)
    unit = int(adb.command("stat", "-f", "-c", "%S", str(volume)).strip())
    if unit <= 0:
        raise HandheldError("Device reported an invalid filesystem allocation unit.")
    unit = max(unit, 4096)
    missing_dirs: set[PurePosixPath] = set()
    for item in entries:
        if item["action"] != "copy":
            continue
        # Reserve rounded file data plus temp/final directory-entry growth.
        item["allocation_bytes"] = ((item["size_bytes"] + unit - 1) // unit + 2) * unit
        parent = (target / item["path"]).parent
        while parent != volume:
            if adb.kind(parent) == "missing":
                missing_dirs.add(parent)
            parent = parent.parent
    additions = sum(item["size_bytes"] for item in entries if item["action"] == "copy")
    # Each new directory may allocate its own contents and grow its parent.
    allocated = sum(item.get("allocation_bytes", 0) for item in entries) + 2 * unit * len(missing_dirs)
    conflicts = sum(item["action"] == "conflict" for item in entries)
    enough = capacity["free_bytes"] - allocated >= reserve
    report = {"serial": adb.serial, "source": str(root), "destination": str(target),
              "apply": apply, "headroom_bytes": reserve, "planned_bytes": additions,
              "planned_allocation_bytes": allocated, "allocation_unit_bytes": unit,
              "space": capacity, "files": entries, "conflict_count": conflicts,
              "capacity_ok": enough, "status": "blocked" if conflicts or not enough else "planned"}
    if not apply or report["status"] == "blocked":
        return report
    for item in entries:
        if item["action"] != "copy":
            continue
        local, remote = root / item["path"], target / item["path"]
        expected = item["size_bytes"], item["sha256"]
        # Revalidate source and target immediately before each mutation.
        if local.is_symlink() or not local.is_file() or (local.stat().st_size, _digest(local)) != expected:
            raise HandheldError(f"Source changed since planning: {local}")
        if adb.check_path(remote) != "missing":
            raise HandheldError(f"Target appeared since planning; rerun safely: {remote}")
        directory_bytes = 2 * unit * sum(
            remote.is_relative_to(directory) and adb.kind(directory) == "missing"
            for directory in missing_dirs)
        if adb.space(volume)["free_bytes"] - item["allocation_bytes"] - directory_bytes < reserve:
            raise HandheldError("Device space changed; requested headroom would be exceeded.")
        if directory_bytes:
            adb.command("mkdir", "-p", str(remote.parent))
        adb.check_path(remote.parent, directory=True)
        temp = PurePosixPath(adb.command("mktemp", str(remote.parent / ".retrofetch-XXXXXXXXXXXX")).strip())
        if temp.parent != remote.parent or not re.fullmatch(r"\.retrofetch-[A-Za-z0-9]+", temp.name):
            raise HandheldError("Device mktemp returned an unsafe path; refusing to touch it.")
        try:
            if adb.space(volume)["free_bytes"] - item["allocation_bytes"] < reserve:
                raise HandheldError("Device space changed; requested headroom would be exceeded.")
            adb.push(local, temp)
            adb.check_path(temp)
            if adb.fingerprint(temp) != expected:
                raise HandheldError(f"Transferred bytes failed SHA256/size verification: {remote}")
            if adb.check_path(remote) != "missing":
                raise HandheldError(f"Target appeared during transfer; refusing to replace it: {remote}")
            # ponytail: mv -n requires a single writer on Android implementations
            # without atomic NOREPLACE; use a native helper if concurrent writers matter.
            adb.command("mv", "-n", str(temp), str(remote))
            if adb.kind(temp) != "missing":
                raise HandheldError(f"No-clobber publication refused; target preserved: {remote}")
            adb.check_path(remote)
            if adb.fingerprint(remote) != expected:
                raise HandheldError(f"Published file verification failed; preserved for inspection: {remote}")
            item["action"] = "copied"
        finally:
            adb.command("rm", "-f", str(temp))
    report["status"] = "complete"
    return report


@app.command("inspect")
def inspect_device(serial: str = typer.Option(..., help="Explicit authorized ADB device serial.")) -> None:
    """Read model, Android, display, shared-volume space and third-party package names."""
    try:
        adb = ADB(serial)
        volumes = []
        for name in adb.children(PurePosixPath("/storage")):
            if name in {"self", "emulated"}:
                continue
            volume = PurePosixPath("/storage") / name
            if adb.kind(volume) == "dir":
                volumes.append(adb.space(volume))
        internal = PurePosixPath("/storage/emulated/0")
        if adb.kind(internal) == "dir":
            volumes.append(adb.space(internal))
        packages = adb.command("pm", "list", "packages", "-3").splitlines()
        if any(not line.startswith("package:") for line in packages):
            raise HandheldError("Unexpected package-manager output; check device authorization.")
        _emit({"serial": serial, "model": adb.command("getprop", "ro.product.model").strip(),
               "android": adb.command("getprop", "ro.build.version.release").strip(),
               "display": {"size": adb.command("wm", "size").strip(),
                           "density": adb.command("wm", "density").strip()},
               "volumes": volumes, "packages": sorted(line[8:] for line in packages)})
    except (ValueError, OSError) as exc:
        _emit({"error": str(exc)})
        raise typer.Exit(2) from exc


@app.command()
def transfer(source: Path,
             destination: str = typer.Option(..., help="Shared /storage/VOLUME/ROMs destination, optionally a subdirectory."),
             serial: str = typer.Option(..., help="Explicit authorized ADB device serial."),
             headroom_gib: float = typer.Option(5.0, help="Minimum free GiB to preserve."),
             apply: bool = typer.Option(False, "--apply", help="Copy verified additions; otherwise only plan.")) -> None:
    """Plan additive size+SHA256 transfers; never overwrite or delete existing ROMs."""
    try:
        _destination(destination)
        if not math.isfinite(headroom_gib) or headroom_gib < 0:
            raise HandheldError("--headroom-gib must be finite and nonnegative.")
        report = transfer_library(source, destination, ADB(serial), headroom_gib, apply)
        _emit(report)
        if report["status"] == "blocked":
            raise typer.Exit(1)
    except (ValueError, OSError) as exc:
        _emit({"error": str(exc)})
        raise typer.Exit(2) from exc


@app.command()
def audit(source: Path) -> None:
    """Report library readiness as JSON (warnings alone do not fail)."""
    try:
        collect_library_files(source)
        report = audit_library(source)
        _emit(report)
    except (ValueError, OSError) as exc:
        _emit({"error": str(exc)})
        raise typer.Exit(2) from exc
    if report["error_count"]:
        raise typer.Exit(1)
