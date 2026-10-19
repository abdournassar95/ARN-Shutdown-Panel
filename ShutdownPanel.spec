# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec — Shutdown Panel host application.

Produces a single-file ``dist/ShutdownPanel.exe`` (referenced by build_exe.py
and installer.iss). Build with::

    python -m PyInstaller --clean --noconfirm ShutdownPanel.spec
"""

import os
import sys
from pathlib import Path

HERE = Path(SPECPATH)  # injected by PyInstaller
ICON = HERE / "assets" / "icon.ico"


def _datas():
    """Bundles the desktop UI (HTML/CSS/JS/fonts/icons) and runtime assets."""
    items = [
        (str(HERE / "gui" / "web"), "gui/web"),
        (str(HERE / "cert"), "cert"),
    ]
    # gui/web already contains assets/icons, but keep the repository-level
    # assets for installers/tools that resolve paths from the bundle root.
    if (HERE / "assets").is_dir():
        items.append((str(HERE / "assets"), "assets"))
    return items


hiddenimports = [
    "webview.platforms.edgechromium",
    "webview.platforms.winforms",
    "pystray._win32",
    "PIL._tkinter_finder",
]

a = Analysis(
    [str(HERE / "main.py")],
    pathex=[str(HERE)],
    binaries=[],
    datas=_datas(),
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "PyQt5", "PyQt6", "PySide2", "PySide6"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="ShutdownPanel",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICON) if ICON.exists() else None,
)
