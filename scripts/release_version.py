"""Normalize the canonical PEP 440 project version for Windows builds."""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path


_VERSION_PATTERN = re.compile(
    r"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)"
    r"(?:(?P<tag>a|b|rc)(?P<serial>[1-9]\d*))?$"
)


@dataclass(frozen=True, slots=True)
class ReleaseVersion:
    public: str
    windows_quad: tuple[int, int, int, int]
    is_prerelease: bool

    @property
    def windows(self) -> str:
        return ".".join(str(part) for part in self.windows_quad)


def resolve_release_version(value: str) -> ReleaseVersion:
    match = _VERSION_PATTERN.fullmatch(value)
    if match is None:
        raise ValueError(
            "Release version must be MAJOR.MINOR.PATCH with optional aN, bN, or rcN"
        )
    core = tuple(
        int(match.group(name)) for name in ("major", "minor", "patch")
    )
    serial_text = match.group("serial")
    revision = int(serial_text) if serial_text is not None else 0
    if any(part > 65535 for part in (*core, revision)):
        raise ValueError("Windows version components must not exceed 65535")
    return ReleaseVersion(
        public=value,
        windows_quad=(*core, revision),
        is_prerelease=serial_text is not None,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version")
    parser.add_argument("--batch-output", type=Path, required=True)
    args = parser.parse_args()
    version = resolve_release_version(args.version)
    args.batch_output.parent.mkdir(parents=True, exist_ok=True)
    args.batch_output.write_text(
        f"WINDOWS_VERSION={version.windows}\n"
        f"IS_PRERELEASE={int(version.is_prerelease)}\n",
        encoding="ascii",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
