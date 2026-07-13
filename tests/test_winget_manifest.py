"""WinGet manifest generation tests."""

from __future__ import annotations

import hashlib

import pytest

from scripts.generate_winget_manifest import PACKAGE_ID, generate


def test_generate_winget_manifest_uses_versioned_url_and_real_hash(tmp_path):
    installer = tmp_path / "OpenCareEyes_Setup_0.4.0.exe"
    installer.write_bytes(b"installer payload")

    files = generate(installer, tmp_path / "out", version="0.4.0")

    assert len(files) == 3
    assert files[0].parent.relative_to(tmp_path / "out").parts == (
        "manifests",
        "o",
        "Odyphus",
        "OpenCareEyes",
        "0.4.0",
    )
    installer_manifest = next(path for path in files if ".installer." in path.name)
    content = installer_manifest.read_text(encoding="utf-8")
    expected_hash = hashlib.sha256(b"installer payload").hexdigest().upper()
    assert PACKAGE_ID in content
    assert "/releases/download/v0.4.0/OpenCareEyes_Setup_0.4.0.exe" in content
    assert expected_hash in content
    assert "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART" in content
    assert (
        "# yaml-language-server: $schema="
        "https://aka.ms/winget-manifest.installer.1.10.0.schema.json"
    ) in content

    headers = {
        path.name: path.read_text(encoding="utf-8").splitlines()[0]
        for path in files
    }
    assert headers[f"{PACKAGE_ID}.yaml"].endswith(
        "winget-manifest.version.1.10.0.schema.json"
    )
    assert headers[f"{PACKAGE_ID}.locale.zh-CN.yaml"].endswith(
        "winget-manifest.defaultLocale.1.10.0.schema.json"
    )


def test_generate_winget_manifest_rejects_prerelease(tmp_path):
    installer = tmp_path / "installer.exe"
    installer.write_bytes(b"payload")

    with pytest.raises(ValueError, match="stable"):
        generate(installer, tmp_path / "out", version="0.4.0-beta.1")
