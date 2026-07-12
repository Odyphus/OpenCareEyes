"""Blue light filter using Windows gamma ramp manipulation."""

import ctypes
import logging

from opencareyes.core.color_temp import kelvin_to_rgb
from opencareyes.core.monitor_manager import MonitorManager
from opencareyes.platform.win32_api import (
    CreateDCW,
    DeleteDC,
    GetDC,
    GetDeviceGammaRamp,
    ReleaseDC,
    SetDeviceGammaRamp,
)

log = logging.getLogger(__name__)

# Gamma ramp: 256 entries per channel (R, G, B) = 768 total unsigned shorts
_RAMP_SIZE = 256
_GammaArray = ctypes.c_ushort * (_RAMP_SIZE * 3)


class BlueLightFilter:
    """Adjusts screen color temperature by manipulating the display gamma ramp."""

    def __init__(self):
        self._original_ramps: dict[str, _GammaArray] = {}
        self._current_temp: int = 6500
        self._enabled: bool = False
        try:
            from PySide6.QtWidgets import QApplication

            app = QApplication.instance()
            if app is not None:
                app.screenAdded.connect(self.refresh_screens)
                app.screenRemoved.connect(self.refresh_screens)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def enable(self, temperature: int = 4500) -> bool:
        """Enable the blue light filter at the given color temperature."""
        if not self._enabled:
            self._capture_original_ramps()
        applied = self.set_temperature(temperature)
        self._enabled = applied
        log.info("Blue light filter enabled at %dK", temperature)
        return applied

    def disable(self) -> bool:
        """Disable the filter and restore the original gamma ramp."""
        restored = True
        if self._enabled and self._original_ramps:
            restored = self._restore_original_ramps()
        self._enabled = False
        self._current_temp = 6500
        log.info("Blue light filter disabled")
        return restored

    def set_temperature(self, kelvin: int) -> bool:
        """Apply a color temperature to all monitors."""
        r, g, b = kelvin_to_rgb(kelvin)
        ramp = self._build_gamma_ramp(r, g, b)
        applied = self._apply_ramp(ramp)
        if applied:
            self._current_temp = kelvin
        return applied

    def refresh_screens(self, *_):
        """Capture newly attached displays and reapply the active filter."""
        if not self._enabled:
            return
        self._capture_original_ramps(overwrite=False)
        self.set_temperature(self._current_temp)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------
    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def current_temperature(self) -> int:
        return self._current_temp

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _build_gamma_ramp(r: float, g: float, b: float) -> _GammaArray:
        """Build a 768-entry gamma ramp array from RGB multipliers."""
        ramp = _GammaArray()
        for i in range(_RAMP_SIZE):
            ramp[i] = min(65535, int(i * r * 257))
            ramp[i + _RAMP_SIZE] = min(65535, int(i * g * 257))
            ramp[i + _RAMP_SIZE * 2] = min(65535, int(i * b * 257))
        return ramp

    def _capture_original_ramps(self, overwrite: bool = True) -> None:
        """Capture each display's gamma ramp before changing it."""
        for name, dc, release_kind in self._open_display_dcs():
            if not overwrite and name in self._original_ramps:
                self._release_dc(dc, release_kind)
                continue
            ramp = _GammaArray()
            if GetDeviceGammaRamp(dc, ctypes.byref(ramp)):
                self._original_ramps[name] = ramp
            else:
                log.warning("GetDeviceGammaRamp failed for %s", name)
            self._release_dc(dc, release_kind)

    def _restore_original_ramps(self) -> bool:
        """Restore original ramps for all displays that are still attached."""
        success = True
        for name, dc, release_kind in self._open_display_dcs():
            ramp = self._original_ramps.get(name)
            if ramp is not None and not SetDeviceGammaRamp(dc, ctypes.byref(ramp)):
                log.warning("SetDeviceGammaRamp restore failed for %s", name)
                success = False
            self._release_dc(dc, release_kind)
        self._original_ramps.clear()
        return success

    def _apply_ramp(self, ramp: _GammaArray) -> bool:
        """Apply a gamma ramp to every attached display."""
        applied = False
        for name, dc, release_kind in self._open_display_dcs():
            if not SetDeviceGammaRamp(dc, ctypes.byref(ramp)):
                log.warning("SetDeviceGammaRamp failed for %s", name)
            else:
                applied = True
            self._release_dc(dc, release_kind)
        return applied

    @staticmethod
    def _open_display_dcs():
        """Return ``(device_name, HDC, release_kind)`` entries."""
        entries = []
        for monitor in MonitorManager().get_monitors():
            name = monitor["name"]
            dc = CreateDCW("DISPLAY", name, None, None)
            if dc:
                entries.append((name, dc, "delete"))
        if not entries:
            dc = GetDC(None)
            if dc:
                entries.append(("virtual-desktop", dc, "release"))
        return entries

    @staticmethod
    def _release_dc(dc, release_kind: str):
        if release_kind == "delete":
            DeleteDC(dc)
        else:
            ReleaseDC(None, dc)
