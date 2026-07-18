"""Release-package attribution regression tests."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


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
