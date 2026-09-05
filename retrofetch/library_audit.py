"""Read-only local-library readiness checks; no extraction or device access."""
from __future__ import annotations

import os
import re
import stat
import unicodedata
from collections import defaultdict
from pathlib import Path, PureWindowsPath

from .catalog import parse_nointro_name

_EXCLUDED = {
    ".retrofetch-state.json", ".retrofetch-staging", ".multidisc-staging",
    ".addons", ".git", "__pycache__", "info.json", "manifest.install",
    "systeminfo.txt", "gamelist.xml",
}
_ARCHIVES = {".zip", ".7z", ".rar", ".tar", ".gz", ".xz"}
_LAUNCH = {".m3u", ".cue", ".chd", ".iso", ".rvz", ".gcz", ".cso", ".pbp", ".nro"}
_CUE_FILE = re.compile(r'FILE\s+(?:"([^"\r\n]+)"|([^"\s]+))\s+\S+\s*', re.IGNORECASE)


def _unsafe_name(name: str) -> bool:
    return "\\" in name or any(unicodedata.category(c) == "Cc" for c in name)


def _excluded(path: Path) -> bool:
    name = path.name.casefold()
    return name in _EXCLUDED or name.startswith(".retrofetch-") or path.suffix.casefold() in {".url", ".desktop"}


def collect_library_files(root: Path) -> list[Path]:
    """Return sorted absolute files, excluding housekeeping; fail closed on unsafe paths.

    Excluded directories are not traversed. Included hidden directories are ordinary
    library content. Symlinks are rejected even when their own name is excluded.
    """
    root = Path(root).absolute()
    try:
        for ancestor in (*reversed(root.parents), root):
            if ancestor.is_symlink():
                raise ValueError(f"Symlink is not allowed: {ancestor}")
        if not root.is_dir():
            raise ValueError(f"Library root is not a directory: {root}")
        root = root.resolve(strict=True)
        files: list[Path] = []
        pending = [root]
        while pending:
            directory = pending.pop()
            names: dict[str, str] = {}
            for path in sorted(directory.iterdir()):
                mode = path.lstat().st_mode
                if stat.S_ISLNK(mode) or not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
                    raise ValueError(f"Not a regular file or directory (symlinks forbidden): {path}")
                if _excluded(path):
                    continue
                if _unsafe_name(path.name):
                    raise ValueError(f"Unsafe Android SD filename: {path}")
                folded = path.name.casefold()
                if folded in names:
                    raise ValueError(f"Casefold collision in {directory}: {names[folded]} / {path.name}")
                names[folded] = path.name
                if stat.S_ISDIR(mode):
                    pending.append(path)
                else:
                    files.append(path)
        return sorted(files)
    except OSError as exc:
        raise ValueError(f"Cannot read library: {exc}") from exc


def _reference(root: Path, playlist: Path, text: str, files: set[Path]) -> Path:
    if (not text or _unsafe_name(text) or Path(text).is_absolute()
            or PureWindowsPath(text).drive or re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", text)):
        raise ValueError("Reference must be a safe relative file path")
    # Check every component before normalizing '..', so a symlink cannot be hidden by it.
    target = playlist.parent
    parts = Path(text).parts
    for index, part in enumerate(parts):
        target = target / part
        if target.is_symlink():
            raise ValueError("Reference traverses a symlink")
        if index < len(parts) - 1 and not target.is_dir():
            raise FileNotFoundError(f"Missing reference directory: {target}")
        target = Path(os.path.abspath(target))
        if not target.is_relative_to(root):
            raise ValueError("Reference escapes the library root")
    if not target.is_file():
        raise FileNotFoundError(f"Missing regular file (paths are case-sensitive): {text}")
    if target not in files:
        raise ValueError("Reference points to excluded library content")
    return target


def audit_library(root: Path) -> dict:
    """Return JSON-safe readiness issues, never changing library content."""
    root = Path(root).absolute()
    issues: list[dict[str, str]] = []
    result: dict = {"root": str(root), "file_count": 0, "total_bytes": 0,
              "error_count": 0, "warning_count": 0, "issues": issues}

    def issue(severity: str, code: str, path: Path, detail: str) -> None:
        display_path = str(path.relative_to(root)) if path.is_relative_to(root) else str(path)
        issues.append({"severity": severity, "code": code, "path": display_path, "detail": detail})
        result[f"{severity}_count"] += 1

    try:
        files = collect_library_files(root)
    except ValueError as exc:
        issue("error", "unsafe_library", root, str(exc))
        return result
    root = root.resolve()
    result["root"] = str(root)
    result["file_count"] = len(files)
    file_set = set(files)
    referenced: set[Path] = set()
    dependencies: dict[Path, list[Path]] = defaultdict(list)
    for path in files:
        suffix = path.suffix.casefold()
        try:
            size = path.stat().st_size
            result["total_bytes"] += size
            if size == 0:
                issue("error", "empty_file", path, "File has zero bytes")
            if suffix in {".part", ".partial", ".crdownload"}:
                issue("error", "partial_download", path, "Incomplete download requires attention")
            if suffix in _ARCHIVES:
                issue("warning", "source_archive", path,
                      "Archive may need preparation for the selected emulator; not evidence of corruption")
            if suffix == ".nro" and len(path.relative_to(root).parts) > 2:
                issue("warning", "nested_nro", path,
                      "Nested NRO may introduce an extra ES-DE folder; review launch layout")
            if suffix not in {".m3u", ".cue"}:
                continue
            text = path.read_text(encoding="utf-8-sig")
            references = []
            for number, raw in enumerate(text.splitlines(), 1):
                line = raw.strip()
                if not line or line.startswith(("#", ";")):
                    continue
                if suffix == ".cue":
                    if not re.match(r"^FILE(?:\s|$)", line, re.IGNORECASE):
                        continue
                    match = _CUE_FILE.fullmatch(line)
                    if not match:
                        issue("error", "malformed_playlist", path, f"Malformed CUE FILE record on line {number}")
                        continue
                    line = match.group(1) or match.group(2)
                references.append((number, line))
            if not references:
                issue("error", "malformed_playlist", path, "Playlist contains no file references")
            for number, reference in references:
                try:
                    target = _reference(root, path, reference, file_set)
                    referenced.add(target)
                    if target.suffix.casefold() in {".m3u", ".cue"}:
                        dependencies[path].append(target)
                except FileNotFoundError as exc:
                    issue("error", "missing_reference", path, f"Line {number}: {exc}")
                except ValueError as exc:
                    issue("error", "unsafe_reference", path, f"Line {number}: {exc}: {reference}")
        except (OSError, UnicodeError) as exc:
            issue("error", "unreadable_playlist" if suffix in {".m3u", ".cue"} else "unreadable_file", path, str(exc))

    # Iterative DFS also handles long chains without Python recursion limits.
    active: set[Path] = set()
    finished: set[Path] = set()
    for start in dependencies:
        stack = [(start, False)]
        while stack:
            node, leaving = stack.pop()
            if leaving:
                active.remove(node)
                finished.add(node)
            elif node in active:
                issue("error", "cyclic_playlist", node, "Playlist dependency cycle; review references")
            elif node not in finished:
                active.add(node)
                stack.append((node, True))
                stack.extend((child, False) for child in reversed(dependencies.get(node, [])))

    # ponytail: filename candidates only; byte identity requires a separate hash audit.
    groups: dict[tuple, list[tuple[Path, int | None]]] = defaultdict(list)
    for path in files:
        relative = path.relative_to(root)
        if path in referenced or path.suffix.casefold() not in _LAUNCH or any(p.startswith(".") for p in relative.parts):
            continue
        parsed = parse_nointro_name(path.name)
        system = relative.parts[0] if len(relative.parts) > 1 else ""
        key = (system, parsed.title.casefold(), tuple(sorted(parsed.regions)),
               parsed.revision, tuple(sorted(parsed.tags)))
        groups[key].append((path, parsed.disc))
    for entries in groups.values():
        discs = {disc for _, disc in entries if disc is not None}
        if len(discs) > 1:
            issue("warning", "multidisc_review", entries[0][0],
                  "Separate disc launch candidates; review ES-DE visibility/emulator handling (not duplicate bytes): "
                  + ", ".join(str(p.relative_to(root)) for p, _ in entries))
        by_disc: dict[int | None, list[Path]] = defaultdict(list)
        for path, disc in entries:
            by_disc[disc].append(path)
        for candidates in by_disc.values():
            if len(candidates) > 1:
                issue("warning", "duplicate_candidate", candidates[0],
                      "Same-release launch candidates, not proven duplicate bytes; review: "
                      + ", ".join(str(p.relative_to(root)) for p in candidates))
    return result
