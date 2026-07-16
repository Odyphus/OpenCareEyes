# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller specification for the portable, single-file Windows build."""

from importlib.metadata import distribution

from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo,
    StringFileInfo,
    StringStruct,
    StringTable,
    VarFileInfo,
    VarStruct,
    VSVersionInfo,
)


_distribution = distribution("opencareyes")
_distribution_path = _distribution._path
_metadata_file = _distribution_path / "METADATA"
_version = _distribution.version
_version_parts = tuple(int(part) for part in _version.split("."))
if len(_version_parts) != 3:
    raise ValueError("OpenCareEyes release builds require MAJOR.MINOR.PATCH")
_version_quad = (*_version_parts, 0)
_version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=_version_quad, prodvers=_version_quad),
    kids=[
        StringFileInfo(
            [
                StringTable(
                    "080404B0",
                    [
                        StringStruct("CompanyName", "Odyphus"),
                        StringStruct(
                            "FileDescription",
                            "OpenCareEyes - Windows 桌面陪伴与护眼助手",
                        ),
                        StringStruct("FileVersion", _version),
                        StringStruct("InternalName", "OpenCareEyes"),
                        StringStruct("LegalCopyright", "Copyright (c) 2026 Odyphus"),
                        StringStruct("OriginalFilename", "OpenCareEyes.exe"),
                        StringStruct("ProductName", "OpenCareEyes"),
                        StringStruct("ProductVersion", _version),
                    ],
                )
            ]
        ),
        VarFileInfo([VarStruct("Translation", [2052, 1200])]),
    ],
)


a = Analysis(
    ["src/opencareyes/__main__.py"],
    pathex=["src"],
    binaries=[],
    datas=[
        ("assets", "assets"),
        ("LICENSE", "."),
        ("THIRD_PARTY_NOTICES.md", "."),
        ("licenses", "licenses"),
        # APP_VERSION only needs METADATA. Copying the editable install's whole
        # dist-info directory would also bundle direct_url.json and leak the
        # build machine's absolute checkout path.
        (str(_metadata_file), _distribution_path.name),
    ],
    hiddenimports=[
        "PySide6.QtNetwork",
        "PySide6.QtSvg",
        "astral",
        "astral.sun",
        "darkdetect",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "pip",
        "pkg_resources",
        "pytest",
        "setuptools",
        "test",
        "tkinter",
        "unittest",
    ],
    noarchive=False,
)

# PyInstaller detects ``importlib.metadata.version("opencareyes")`` and
# automatically collects the whole editable-install dist-info directory.  In
# addition to being unnecessary at runtime, its direct_url.json contains the
# absolute source checkout path.  Retain only the canonical METADATA file used
# by APP_VERSION and discard every other automatically collected project
# metadata file.
_metadata_destination = f"{_distribution_path.name}/METADATA".lower()
_metadata_prefix = f"{_distribution_path.name}/".lower()
_metadata_seen = False
_filtered_datas = []
for entry in a.datas:
    destination = entry[0].replace("\\", "/").lower()
    if destination.startswith(_metadata_prefix):
        if destination == _metadata_destination and not _metadata_seen:
            _filtered_datas.append(entry)
            _metadata_seen = True
        continue
    _filtered_datas.append(entry)
if not _metadata_seen:
    raise ValueError("OpenCareEyes METADATA was not collected for the build")
a.datas = _filtered_datas

# Never bundle system libraries discovered through an unrelated global Python
# or PATH entry (for example Anaconda). Windows 10/11 provide UCRT and ICU;
# shipping foreign copies can prevent QtCore from loading before the
# application entry point is reached.
_system_libraries = {"ucrtbase.dll", "icuuc.dll"}
_unused_qt_binaries = {
    # PySide6's generic plugin hook pulls these QML/Quick/PDF dependencies in
    # through optional plugins. OpenCareEyes uses Widgets, SVG icons and local
    # sockets only, so extracting them on every one-file launch adds startup
    # cost without providing a reachable feature.
    "pyside6/qt6pdf.dll",
    "pyside6/qt6qml.dll",
    "pyside6/qt6qmlmeta.dll",
    "pyside6/qt6qmlmodels.dll",
    "pyside6/qt6qmlworkerscript.dll",
    "pyside6/qt6quick.dll",
    "pyside6/qt6virtualkeyboard.dll",
    "pyside6/opengl32sw.dll",
    "pyside6/plugins/generic/qtuiotouchplugin.dll",
    "pyside6/plugins/imageformats/qpdf.dll",
    "pyside6/plugins/platforminputcontexts/qtvirtualkeyboardplugin.dll",
    "pyside6/plugins/platforms/qdirect2d.dll",
    "pyside6/plugins/platforms/qminimal.dll",
}
a.binaries = [
    entry
    for entry in a.binaries
    if entry[0].lower() not in _system_libraries
    and not entry[0].lower().startswith("icudt")
    and entry[0].replace("\\", "/").lower() not in _unused_qt_binaries
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
    version=_version_info,
    uac_admin=False,
    runtime_tmpdir=None,
)
