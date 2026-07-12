"""Application-wide constants."""

import os
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

APP_NAME = "OpenCareEyes"
ORG_NAME = "OpenCareEyes"

try:
    APP_VERSION = version("opencareyes")
except PackageNotFoundError:
    # Editable/source-tree runs may not have package metadata yet. Read the
    # canonical value directly instead of duplicating a release version here.
    project_table = False
    APP_VERSION = "0+unknown"
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    if pyproject.is_file():
        for raw_line in pyproject.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if line.startswith("["):
                project_table = line == "[project]"
            elif project_table and line.startswith("version") and "=" in line:
                APP_VERSION = line.split("=", 1)[1].strip().strip('"\'')
                break

# Paths
if getattr(sys, "frozen", False):
    # PyInstaller bundles assets into sys._MEIPASS
    BASE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
else:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ASSETS_DIR = os.path.join(BASE_DIR, "assets")
ICONS_DIR = os.path.join(ASSETS_DIR, "icons")
SOUNDS_DIR = os.path.join(ASSETS_DIR, "sounds")
STYLES_DIR = os.path.join(ASSETS_DIR, "styles")

# Color temperature range (Kelvin)
TEMP_MIN = 1000
TEMP_MAX = 6500
TEMP_DEFAULT = 6500

# Dimmer range (0 = no dim, 200 = max dim)
DIM_MIN = 0
DIM_MAX = 200
DIM_DEFAULT = 0

# Break reminder defaults (seconds)
WORK_DURATION_DEFAULT = 45 * 60
BREAK_DURATION_DEFAULT = 3 * 60
MICRO_BREAK_INTERVAL_DEFAULT = 20 * 60
MICRO_BREAK_DURATION_DEFAULT = 20

# Focus mode
FOCUS_DIM_DEFAULT = 150

# Hotkey defaults
HOTKEY_TOGGLE_FILTER = "ctrl+alt+n"
HOTKEY_TOGGLE_BREAK = "ctrl+alt+b"
HOTKEY_TOGGLE_DIMMER = "ctrl+alt+d"
HOTKEY_TOGGLE_FOCUS = "ctrl+alt+f"

# Windows registry
AUTOSTART_REG_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
AUTOSTART_REG_NAME = APP_NAME
