"""Archive extraction via py7zr, rarfile, and zipfile."""

from __future__ import annotations

import logging
import zipfile
from pathlib import Path

from retrofetch.sanitize import sanitize_filename

_log = logging.getLogger(__name__)

_IGNORABLE_SUFFIXES = (".txt", ".nfo", ".md", ".diz", ".sfv", ".ds_store")


class ExtractionError(Exception):
    """Raised when archive extraction fails or yields no usable payload."""


def _is_ignorable(name: str) -> bool:
    lc = name.lower()
    if lc.endswith(_IGNORABLE_SUFFIXES):
        return True
    base = Path(lc).name
    return base in {"readme", "license"}


def is_archive(path: Path) -> bool:
    suffixes = [s.lower() for s in path.suffixes]
    if not suffixes:
        return False
    last = suffixes[-1]
    return last in (".zip", ".7z", ".rar") or (
        len(suffixes) >= 2 and suffixes[-2] == ".tar"
    )


def _extract_zip(archive: Path, dest: Path) -> list[Path]:
    out: list[Path] = []
    with zipfile.ZipFile(archive) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            if _is_ignorable(info.filename):
                continue
            safe_name = sanitize_filename(Path(info.filename).name)
            target = dest / safe_name
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as dst:
                while True:
                    chunk = src.read(1024 * 1024)
                    if not chunk:
                        break
                    dst.write(chunk)
            out.append(target)
    return out


def _extract_7z(archive: Path, dest: Path) -> list[Path]:
    try:
        import py7zr
    except ImportError as exc:
        raise ExtractionError(f"py7zr not installed: {exc}") from exc
    out: list[Path] = []
    with py7zr.SevenZipFile(archive, mode="r") as sz:
        names = sz.getnames()
        filtered = [n for n in names if not _is_ignorable(n)]
        sz.extract(path=str(dest), targets=filtered)
    for name in filtered:
        src_path = dest / name
        if not src_path.exists():
            continue
        safe_name = sanitize_filename(Path(name).name)
        target = dest / safe_name
        if src_path != target:
            src_path.replace(target)
        out.append(target)
    return out


def _extract_rar(archive: Path, dest: Path) -> list[Path]:
    try:
        import rarfile
    except ImportError as exc:
        raise ExtractionError(f"rarfile not installed: {exc}") from exc
    out: list[Path] = []
    try:
        with rarfile.RarFile(archive) as rf:
            for info in rf.infolist():
                if info.is_dir():
                    continue
                if _is_ignorable(info.filename):
                    continue
                safe_name = sanitize_filename(Path(info.filename).name)
                target = dest / safe_name
                with rf.open(info) as src, open(target, "wb") as dst:
                    while True:
                        chunk = src.read(1024 * 1024)
                        if not chunk:
                            break
                        dst.write(chunk)
                out.append(target)
    except rarfile.Error as exc:
        raise ExtractionError(f"rar extraction failed: {exc}") from exc
    return out


def extract_archive(archive: Path, dest: Path) -> list[Path]:
    archive = Path(archive)
    dest = Path(dest)
    if not archive.exists():
        raise ExtractionError(f"archive not found: {archive}")
    suffixes = [s.lower() for s in archive.suffixes]
    last = suffixes[-1] if suffixes else ""
    try:
        if last == ".zip":
            files = _extract_zip(archive, dest)
        elif last == ".7z":
            files = _extract_7z(archive, dest)
        elif last == ".rar":
            files = _extract_rar(archive, dest)
        else:
            raise ExtractionError(f"unsupported archive type: {archive.suffix}")
    except ExtractionError:
        raise
    except Exception as exc:
        raise ExtractionError(f"extraction failed for {archive.name}: {exc}") from exc
    if not files:
        raise ExtractionError(f"archive had no usable payload: {archive.name}")
    return files
