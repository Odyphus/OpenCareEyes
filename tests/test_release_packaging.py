"""Release-package attribution regression tests."""

from __future__ import annotations

from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 compatibility
    import tomli as tomllib


ROOT = Path(__file__).resolve().parents[1]


def test_beta_is_the_single_project_version_source():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert project["project"]["version"] == "0.8.0b2"


def test_prerelease_build_uses_numeric_windows_version_and_skips_winget():
    build_script = (ROOT / "build.bat").read_text(encoding="utf-8")
    installer = (ROOT / "installer.iss").read_text(encoding="utf-8")
    spec = (ROOT / "opencareyes.spec").read_text(encoding="utf-8")
    workflow = (
        ROOT / ".github" / "workflows" / "windows-ci.yml"
    ).read_text(encoding="utf-8")

    assert "WINDOWS_VERSION" in build_script
    assert "/DMyWindowsVersion=%WINDOWS_VERSION%" in build_script
    assert 'if "%IS_PRERELEASE%"=="1"' in build_script
    assert "Pre-release build; WinGet generation skipped." in build_script
    assert "VersionInfoVersion={#MyWindowsVersion}" in installer
    assert "#define MyWindowsVersion MyAppVersion" in installer
    assert 'StringStruct("FileVersion", _release_version.windows)' in spec
    assert "$windowsVersion = python -c" in workflow
    assert "resolve_release_version(sys.argv[1]).windows" in workflow
    assert '"/DMyWindowsVersion=$windowsVersion"' in workflow


def test_installer_can_replace_the_running_tray_executable_during_upgrade():
    installer = (ROOT / "installer.iss").read_text(encoding="utf-8")

    assert "CloseApplications=force" in installer
    assert "CloseApplicationsFilter={#MyAppExeName}" in installer
    assert "RestartApplications=no" in installer


def test_portable_packaging_uses_an_ascii_safe_usage_guide_name():
    build_script = (ROOT / "build.bat").read_text(encoding="utf-8")

    assert "FromBase64String('5L2/55So6K+05piOLm1k')" in build_script
    assert "(Join-Path $PWD $guideName)" in build_script


def test_stable_build_path_still_contains_winget_generation():
    build_script = (ROOT / "build.bat").read_text(encoding="utf-8")

    assert r"scripts\generate_winget_manifest.py" in build_script


def test_third_party_license_bundle_has_required_full_texts():
    notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    expected = {
        "LGPL-3.0-only.txt": "GNU LESSER GENERAL PUBLIC LICENSE",
        "GPL-3.0-only.txt": "GNU GENERAL PUBLIC LICENSE",
        "PYINSTALLER-COPYING.txt": "Bootloader Exception",
        "PYTHON-PSF.txt": "PYTHON SOFTWARE FOUNDATION LICENSE VERSION 2",
        "darkdetect-BSD-3-Clause.txt": "Copyright (c) 2019, Alberto Sottile",
    }

    for name, marker in expected.items():
        assert name in notices
        assert marker in (ROOT / "licenses" / name).read_text(encoding="utf-8")


def test_build_script_hashing_does_not_depend_on_optional_powershell_cmdlet():
    script = (ROOT / "build.bat").read_text(encoding="utf-8")

    assert "Get-FileHash" not in script
    assert "$ErrorActionPreference = 'Stop'" in script
    assert "[Security.Cryptography.SHA256]::Create()" in script
    assert "if errorlevel 1 goto :error" in script
    assert "if ('%BUILT_PORTABLE%' -eq '1')" in script


def test_local_and_release_portable_archives_include_license_bundle():
    build_script = (ROOT / "build.bat").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "windows-ci.yml").read_text(encoding="utf-8")

    assert "OpenCareEyes_Portable_%APP_VERSION%.zip" in build_script
    assert "'THIRD_PARTY_NOTICES.md', 'licenses'" in build_script
    assert "OpenCareEyes_Portable_$version.zip" in workflow
    portable_block = workflow[
        workflow.index("Compress-Archive -LiteralPath @(") : workflow.index(
            ') -DestinationPath ".\\OpenCareEyes_Portable_$version.zip"'
        )
    ]
    assert "'.\\licenses'" in portable_block
