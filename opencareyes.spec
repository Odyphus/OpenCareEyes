# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec file for OpenCareEyes — single-file build."""

import os

block_cipher = None

a = Analysis(
    ['src/opencareyes/__main__.py'],
    pathex=['src'],
    binaries=[],
    datas=[
        ('assets', 'assets'),
    ],
    hiddenimports=[
        'PySide6.QtSvg',
        'PySide6.QtNetwork',
        'keyboard',
        'astral',
        'astral.sun',
        'darkdetect',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'unittest',
        'pytest',
        'test',
    ],
    noarchive=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='OpenCareEyes',
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
    icon='assets/icons/opencareyes.ico',
    uac_admin=False,
    runtime_tmpdir=None,
)
