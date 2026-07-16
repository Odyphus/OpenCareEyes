"""System-aware theme and motion preference projection.

The rest of the UI consumes :class:`ThemeSnapshot` instead of independently
guessing the system theme, high-contrast state, or animation preference.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import os
from typing import Callable, Literal

from PySide6.QtCore import QObject, Signal

log = logging.getLogger(__name__)

ThemeRequest = Literal["system", "light", "dark"]
ResolvedTheme = Literal["light", "dark"]
MotionMode = Literal["system", "standard", "reduced"]
MotionProfile = Literal["standard", "reduced"]

BRAND_ACCENT = "#5B8DEF"
WARM_ACCENT = "#F2A65A"
DEFAULT_PET_ACCENT = "#65BFA5"


def system_theme() -> ResolvedTheme:
    """Return the operating-system colour preference with a safe fallback."""

    try:
        import darkdetect

        return "dark" if darkdetect.isDark() else "light"
    except Exception:
        log.debug("Could not read the system colour preference", exc_info=True)
        return "dark"


def client_area_animations_enabled() -> bool:
    """Return the Windows client-area animation preference."""

    if os.name != "nt":
        return True
    try:
        import ctypes

        enabled = ctypes.c_int()
        success = ctypes.windll.user32.SystemParametersInfoW(
            0x1042,  # SPI_GETCLIENTAREAANIMATION
            0,
            ctypes.byref(enabled),
            0,
        )
        return bool(enabled.value) if success else True
    except Exception:
        log.debug("Could not read the Windows animation preference", exc_info=True)
        return True


def battery_saver_enabled() -> bool:
    """Return whether Windows has entered battery-saver mode."""

    if os.name != "nt":
        return False
    try:
        import ctypes
        import ctypes.wintypes as wintypes

        class SystemPowerStatus(ctypes.Structure):
            _fields_ = [
                ("ACLineStatus", wintypes.BYTE),
                ("BatteryFlag", wintypes.BYTE),
                ("BatteryLifePercent", wintypes.BYTE),
                ("SystemStatusFlag", wintypes.BYTE),
                ("BatteryLifeTime", wintypes.DWORD),
                ("BatteryFullLifeTime", wintypes.DWORD),
            ]

        status = SystemPowerStatus()
        return bool(
            ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status))
            and status.SystemStatusFlag == 1
        )
    except Exception:
        log.debug("Could not read the Windows battery-saver state", exc_info=True)
        return False


def high_contrast_enabled() -> bool:
    """Return the Windows high-contrast preference without changing it."""

    if os.name != "nt":
        return False
    try:
        import ctypes
        import ctypes.wintypes as wintypes

        class HighContrast(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.UINT),
                ("dwFlags", wintypes.DWORD),
                ("lpszDefaultScheme", wintypes.LPWSTR),
            ]

        value = HighContrast()
        value.cbSize = ctypes.sizeof(value)
        success = ctypes.windll.user32.SystemParametersInfoW(
            0x0042,  # SPI_GETHIGHCONTRAST
            value.cbSize,
            ctypes.byref(value),
            0,
        )
        return bool(success and value.dwFlags & 0x00000001)
    except Exception:
        log.debug("Could not read the Windows high-contrast preference", exc_info=True)
        return False


@dataclass(frozen=True, slots=True)
class ThemeSnapshot:
    """Resolved, presentation-only theme state shared by every window."""

    requested: ThemeRequest
    resolved: ResolvedTheme
    high_contrast: bool
    motion_profile: MotionProfile
    brand_accent: str = BRAND_ACCENT
    warm_accent: str = WARM_ACCENT
    pet_accent: str = DEFAULT_PET_ACCENT


class ThemeManager(QObject):
    """Project system and user preferences into one immutable snapshot."""

    snapshot_changed = Signal(object)

    def __init__(
        self,
        *,
        theme_detector: Callable[[], str] = system_theme,
        high_contrast_detector: Callable[[], bool] = high_contrast_enabled,
        animation_detector: Callable[[], bool] = client_area_animations_enabled,
        battery_saver_detector: Callable[[], bool] = battery_saver_enabled,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._theme_detector = theme_detector
        self._high_contrast_detector = high_contrast_detector
        self._animation_detector = animation_detector
        self._battery_saver_detector = battery_saver_detector
        self._requested: ThemeRequest = "system"
        self._motion_mode: MotionMode = "system"
        self._pet_accent = DEFAULT_PET_ACCENT
        self._snapshot = self._project()

    @property
    def snapshot(self) -> ThemeSnapshot:
        return self._snapshot

    @property
    def motion_mode(self) -> MotionMode:
        return self._motion_mode

    def set_preferences(
        self,
        *,
        theme: str | None = None,
        motion_mode: str | None = None,
        pet_accent: str | None = None,
    ) -> ThemeSnapshot:
        """Update user presentation preferences and publish semantic changes."""

        if theme is not None:
            self._requested = _normalise_theme(theme)
        if motion_mode is not None:
            self._motion_mode = _normalise_motion_mode(motion_mode)
        if pet_accent is not None:
            self._pet_accent = _normalise_accent(pet_accent)
        return self._refresh_snapshot()

    def refresh_system_preferences(self) -> ThemeSnapshot:
        """Re-evaluate system-owned preferences without changing user choices."""

        return self._refresh_snapshot()

    def _refresh_snapshot(self) -> ThemeSnapshot:
        candidate = self._project()
        if candidate != self._snapshot:
            self._snapshot = candidate
            self.snapshot_changed.emit(candidate)
        return self._snapshot

    def _project(self) -> ThemeSnapshot:
        resolved: ResolvedTheme
        if self._requested == "system":
            detected = self._theme_detector()
            resolved = "light" if detected == "light" else "dark"
        else:
            resolved = self._requested

        animations_enabled = bool(self._animation_detector()) and not bool(
            self._battery_saver_detector()
        )
        motion_profile: MotionProfile = (
            "standard"
            if self._motion_mode == "standard"
            or (self._motion_mode == "system" and animations_enabled)
            else "reduced"
        )
        return ThemeSnapshot(
            requested=self._requested,
            resolved=resolved,
            high_contrast=bool(self._high_contrast_detector()),
            motion_profile=motion_profile,
            pet_accent=self._pet_accent,
        )


def _normalise_theme(value: str) -> ThemeRequest:
    return value if value in {"system", "light", "dark"} else "system"  # type: ignore[return-value]


def _normalise_motion_mode(value: str) -> MotionMode:
    return value if value in {"system", "standard", "reduced"} else "system"  # type: ignore[return-value]


def _normalise_accent(value: str) -> str:
    candidate = str(value).strip().upper()
    if len(candidate) == 7 and candidate.startswith("#"):
        try:
            int(candidate[1:], 16)
        except ValueError:
            pass
        else:
            return candidate
    return DEFAULT_PET_ACCENT
