# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller specification for the portable, single-file Windows build."""

from PyInstaller.utils.hooks import copy_metadata


a = Analysis(
    ["src/opencareyes/__main__.py"],
    pathex=["src"],
    binaries=[],
    datas=[
        ("assets", "assets"),
        *copy_metadata("opencareyes"),
    ],
    hiddenimports=[
        "PySide6.QtNetwork",
        "PySide6.QtSvg",
        "astral",
        "astral.sun",
        "darkdetect",
        "keyboard",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "test", "tkinter", "unittest"],
    noarchive=False,
)

# Never bundle system libraries discovered through an unrelated global Python
# or PATH entry (for example Anaconda). Windows 10/11 provide UCRT and ICU;
# shipping foreign copies can prevent QtCore from loading before the
# application entry point is reached.
_system_libraries = {"ucrtbase.dll", "icuuc.dll"}
a.binaries = [
    entry
    for entry in a.binaries
    if entry[0].lower() not in _system_libraries
    and not entry[0].lower().startswith("icudt")
]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="OpenCareEyes",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="assets/icons/opencareyes.ico",
    uac_admin=False,
    runtime_tmpdir=None,
)
