"""Generate WinGet multi-file manifests from a built Inno Setup installer."""

from __future__ import annotations

import argparse
import hashlib
import re
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib


PACKAGE_ID = "Odyphus.OpenCareEyes"
REPOSITORY = "https://github.com/Odyphus/OpenCareEyes"
_STABLE_VERSION = re.compile(r"^\d+\.\d+\.\d+$")
_MANIFEST_VERSION = "1.10.0"


def project_version(pyproject: Path) -> str:
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    return str(data["project"]["version"])


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def generate(
    installer: Path,
    output_root: Path,
    *,
    version: str,
) -> tuple[Path, ...]:
    if not _STABLE_VERSION.fullmatch(version):
        raise ValueError("WinGet manifests require a stable MAJOR.MINOR.PATCH version")
    if not installer.is_file():
        raise FileNotFoundError(installer)

    # Use the exact winget-pkgs submission layout so the generated tree can be
    # validated and copied without a manual reshape.
    destination = (
        output_root
        / "manifests"
        / "o"
        / "Odyphus"
        / "OpenCareEyes"
        / version
    )
    destination.mkdir(parents=True, exist_ok=True)
    installer_url = (
        f"{REPOSITORY}/releases/download/v{version}/{installer.name}"
    )
    installer_hash = sha256(installer)

    files = {
        f"{PACKAGE_ID}.yaml": f"""# yaml-language-server: $schema=https://aka.ms/winget-manifest.version.{_MANIFEST_VERSION}.schema.json
PackageIdentifier: {PACKAGE_ID}
PackageVersion: {version}
DefaultLocale: zh-CN
ManifestType: version
ManifestVersion: {_MANIFEST_VERSION}
""",
        f"{PACKAGE_ID}.installer.yaml": f"""# yaml-language-server: $schema=https://aka.ms/winget-manifest.installer.{_MANIFEST_VERSION}.schema.json
PackageIdentifier: {PACKAGE_ID}
PackageVersion: {version}
MinimumOSVersion: 10.0.17763.0
InstallerType: inno
Scope: user
UpgradeBehavior: install
Installers:
  - Architecture: x64
    InstallerUrl: {installer_url}
    InstallerSha256: {installer_hash}
    InstallerSwitches:
      Silent: /VERYSILENT /SUPPRESSMSGBOXES /NORESTART
      SilentWithProgress: /SILENT /SUPPRESSMSGBOXES /NORESTART
ManifestType: installer
ManifestVersion: {_MANIFEST_VERSION}
""",
        f"{PACKAGE_ID}.locale.zh-CN.yaml": f"""# yaml-language-server: $schema=https://aka.ms/winget-manifest.defaultLocale.{_MANIFEST_VERSION}.schema.json
PackageIdentifier: {PACKAGE_ID}
PackageVersion: {version}
PackageLocale: zh-CN
Publisher: Odyphus
PublisherUrl: https://github.com/Odyphus
PublisherSupportUrl: {REPOSITORY}/issues
PackageName: OpenCareEyes
PackageUrl: {REPOSITORY}
License: Apache-2.0
LicenseUrl: {REPOSITORY}/blob/v{version}/LICENSE
ShortDescription: 本地优先、低打扰的 Windows 屏幕舒适度与休息提醒助手
Description: 调节屏幕色调与明暗、提供活动加权休息提醒，并在全屏、锁屏或离开电脑时智能暂停。
Tags:
  - eye-comfort
  - break-reminder
  - local-first
  - windows
ReleaseNotesUrl: {REPOSITORY}/releases/tag/v{version}
ManifestType: defaultLocale
ManifestVersion: {_MANIFEST_VERSION}
""",
    }
    written = []
    for name, content in files.items():
        path = destination / name
        path.write_text(content, encoding="utf-8", newline="\n")
        written.append(path)
    return tuple(written)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("installer", type=Path)
    parser.add_argument("--output", type=Path, default=Path("winget_output"))
    parser.add_argument("--version")
    parser.add_argument("--pyproject", type=Path, default=Path("pyproject.toml"))
    args = parser.parse_args()
    version = args.version or project_version(args.pyproject)
    for path in generate(args.installer, args.output, version=version):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
