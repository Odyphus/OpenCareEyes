"""Blue light filter using Windows gamma ramp manipulation."""

import ctypes
import logging

from opencareyes.core.color_temp import kelvin_to_rgb
from opencareyes.platform.win32_api import (
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
        self._original_ramp: _GammaArray | None = None
        self._current_temp: int = 6500
        self._enabled: bool = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def enable(self, temperature: int = 4500) -> None:
        """Enable the blue light filter at the given color temperature."""
        if not self._enabled:
            self._save_original_ramp()
        self.set_temperature(temperature)
        self._enabled = True
        log.info("Blue light filter enabled at %dK", temperature)

    def disable(self) -> None:
        """Disable the filter and restore the original gamma ramp."""
        if self._enabled and self._original_ramp is not None:
            self._restore_original_ramp()
        self._enabled = False
        self._current_temp = 6500
        log.info("Blue light filter disabled")

    def set_temperature(self, kelvin: int) -> None:
        """Apply a color temperature to all monitors."""
        r, g, b = kelvin_to_rgb(kelvin)
        ramp = self._build_gamma_ramp(r, g, b)
        self._apply_ramp(ramp)
        self._current_temp = kelvin

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

    def _save_original_ramp(self) -> None:
        """Capture the current gamma ramp so it can be restored later."""
        dc = self._get_screen_dc()
        if not dc:
            log.warning("Failed to get screen DC for saving gamma ramp")
            return
        try:
            ramp = _GammaArray()
            if GetDeviceGammaRamp(dc, ctypes.byref(ramp)):
                self._original_ramp = ramp
            else:
                log.warning("GetDeviceGammaRamp failed")
        finally:
            ReleaseDC(None, dc)

    def _restore_original_ramp(self) -> None:
        """Restore the previously saved gamma ramp."""
        if self._original_ramp is None:
            return
        self._apply_ramp(self._original_ramp)
        self._original_ramp = None

    def _apply_ramp(self, ramp: _GammaArray) -> None:
        """Apply a gamma ramp to the screen DC."""
        dc = self._get_screen_dc()
        if not dc:
            log.warning("Failed to get screen DC for applying gamma ramp")
            return
        try:
            if not SetDeviceGammaRamp(dc, ctypes.byref(ramp)):
                log.warning("SetDeviceGammaRamp failed")
        finally:
            ReleaseDC(None, dc)

    @staticmethod
    def _get_screen_dc():
        """Get the device context for the entire screen."""
        return GetDC(None)
