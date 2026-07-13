# OpenCareEyes third-party notices

OpenCareEyes is licensed under Apache-2.0. Its Windows binaries also contain
unmodified upstream runtime libraries and a PyInstaller bootloader. The
licenses below apply only to their respective components; they do not replace
the OpenCareEyes project license.

Release maintainers must refresh this list when packaged dependencies change.

| Component | License | Source and license text |
|---|---|---|
| Python 3 runtime | PSF License Version 2 and historical notices | [python.org](https://www.python.org/) · [full text](licenses/PYTHON-PSF.txt) |
| PyInstaller bootloader | GPL-2.0-or-later WITH Bootloader-exception | [pyinstaller.org](https://pyinstaller.org/) · [full text and exception](licenses/PYINSTALLER-COPYING.txt) |
| PySide6, Shiboken6 and Qt 6 libraries | LGPL-3.0-only OR the applicable GPL option | [Qt for Python](https://doc.qt.io/qtforpython-6/licenses.html) · [LGPL v3](licenses/LGPL-3.0-only.txt) · [GPL v3](licenses/GPL-3.0-only.txt) |
| Astral | Apache-2.0 | [upstream source](https://github.com/sffjunkie/astral) · the full Apache-2.0 text is in the repository root [LICENSE](LICENSE) |
| tzdata (including IANA time-zone data) | Apache-2.0 | [upstream source](https://github.com/python/tzdata) · copyright 2020 Paul Ganssle (Google); the full Apache-2.0 text is in the repository root [LICENSE](LICENSE) |
| darkdetect | BSD-3-Clause | [upstream source](https://github.com/albertosottile/darkdetect) · [full text](licenses/darkdetect-BSD-3-Clause.txt) |

OpenCareEyes does not modify the PySide6, Shiboken6 or Qt libraries. The source
for the corresponding upstream versions is available from the linked official
repositories. OpenCareEyes source and build instructions are in
the project repository. Nothing in the application terms prohibits reverse
engineering of those libraries for debugging user modifications.

This notice is an inventory of redistributed software, not legal advice.
