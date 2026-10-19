# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec — Shutdown Panel remote client.

Produces a single-file ``dist/ShutdownPanelClient.exe`` (referenced by
build_exe.py and installer.iss). Build with::

    python -m PyInstaller --clean --noconfirm ShutdownPanelClient.spec
"""

from pathlib import Path

HERE = Path(SPECPATH)  # injected by PyInstaller
ICON = HERE / "assets" / "icon.ico"

datas = [
    (str(HERE / "gui" / "client_web"), "gui/client_web"),
]

hiddenimports = [
    "webview.platforms.edgechromium",
    "webview.platforms.winforms",
    "PIL._tkinter_finder",
]

a = Analysis(
    [str(HERE / "client_main.py")],
    pathex=[str(HERE)],
    binaries=[],
    datas=datas,
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
    name="ShutdownPanelClient",
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
