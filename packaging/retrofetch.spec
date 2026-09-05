# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import sys

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules


ROOT = Path(SPEC).resolve().parent.parent

datas = [
    (str(ROOT / "consoles.yml"), "retrofetch"),
    (str(ROOT / "config.yml.example"), "retrofetch"),
    (str(ROOT / "overrides.yml.example"), "retrofetch"),
    (str(ROOT / ".env.example"), "retrofetch"),
    (str(ROOT / "dats"), "retrofetch/dats"),
    (str(ROOT / "retrofetch" / "tui" / "styles.tcss"), "retrofetch/tui"),
]
datas += collect_data_files("textual")
datas += collect_data_files("internetarchive")

curl_datas, curl_binaries, curl_hidden = collect_all("curl_cffi")
datas += curl_datas

a = Analysis(
    [str(ROOT / "retrofetch" / "windows_entry.py")],
    pathex=[str(ROOT)],
    binaries=curl_binaries,
    datas=datas,
    hiddenimports=(
        collect_submodules("retrofetch.sources")
        + collect_submodules("selectolax")
        + ["internetarchive"]
        + curl_hidden
    ),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest"],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Retrofetch",
    icon=str(ROOT / "packaging" / "retrofetch.ico") if sys.platform == "win32" else None,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
