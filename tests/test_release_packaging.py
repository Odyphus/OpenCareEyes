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
