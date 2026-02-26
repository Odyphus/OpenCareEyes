"""Monitor enumeration and information via Win32 API."""

import ctypes
import ctypes.wintypes as wintypes
import logging

from opencareyes.platform.win32_api import (
    MONITORENUMPROC,
    MONITORINFOEXW,
    EnumDisplayMonitors,
    GetMonitorInfoW,
    MONITORINFOF_PRIMARY,
)

log = logging.getLogger(__name__)


class MonitorManager:
    """Enumerates and stores information about connected display monitors."""

    def __init__(self):
        self._monitors: list[dict] = []

    def refresh(self) -> None:
        """Re-enumerate all connected monitors."""
        self._monitors.clear()
        monitors = self._monitors  # local ref for closure

        @MONITORENUMPROC
        def _callback(hmonitor, hdc, lprect, lparam):
            info = MONITORINFOEXW()
            info.cbSize = ctypes.sizeof(MONITORINFOEXW)
            if GetMonitorInfoW(hmonitor, ctypes.byref(info)):
                rc = info.rcMonitor
                monitors.append({
                    "handle": int(hmonitor),
                    "name": info.szDevice,
                    "geometry": {
                        "left": rc.left,
                        "top": rc.top,
                        "right": rc.right,
                        "bottom": rc.bottom,
                    },
                    "is_primary": bool(info.dwFlags & MONITORINFOF_PRIMARY),
                })
            return True  # continue enumeration

        try:
            EnumDisplayMonitors(None, None, _callback, 0)
        except Exception:
            log.exception("Failed to enumerate monitors")

    def get_monitors(self) -> list[dict]:
        """Return a list of monitor info dicts.

        Each dict contains:
            handle     - HMONITOR handle (int)
            name       - device name string
            geometry   - dict with left, top, right, bottom
            is_primary - bool
        """
        if not self._monitors:
            self.refresh()
        return list(self._monitors)

    def get_monitor_count(self) -> int:
        if not self._monitors:
            self.refresh()
        return len(self._monitors)
