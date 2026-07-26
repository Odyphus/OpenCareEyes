"""Release-version normalization tests."""

from __future__ import annotations

import pytest

from scripts.release_version import resolve_release_version


def test_beta_version_uses_numeric_windows_build_revision():
    version = resolve_release_version("0.8.0b1")

    assert version.public == "0.8.0b1"
    assert version.windows == "0.8.0.1"
    assert version.windows_quad == (0, 8, 0, 1)
    assert version.is_prerelease is True


def test_stable_version_keeps_zero_windows_revision_and_winget_eligibility():
    version = resolve_release_version("0.8.0")

    assert version.public == "0.8.0"
    assert version.windows == "0.8.0.0"
    assert version.windows_quad == (0, 8, 0, 0)
    assert version.is_prerelease is False


@pytest.mark.parametrize(
    "value",
    ("0.8", "0.8.0-beta.1", "v0.8.0", "0.8.0.dev1", "0.8.0b0"),
)
def test_release_version_rejects_unsupported_forms(value):
    with pytest.raises(ValueError, match="MAJOR.MINOR.PATCH"):
        resolve_release_version(value)
