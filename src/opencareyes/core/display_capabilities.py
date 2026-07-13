"""Aggregate Windows advanced-colour capability detection.

The UI deliberately exposes one global display policy.  Internally we still
need to inspect every active target because ``SetDeviceGammaRamp`` has
undefined behaviour as soon as any target is running in an HDR mode.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
from dataclasses import dataclass


QDC_ONLY_ACTIVE_PATHS = 0x00000002
ERROR_SUCCESS = 0
ERROR_INSUFFICIENT_BUFFER = 122
DISPLAYCONFIG_GET_ADVANCED_COLOR_INFO = 9
DISPLAYCONFIG_GET_ADVANCED_COLOR_INFO_2 = 15
DISPLAYCONFIG_ADVANCED_COLOR_MODE_HDR = 2


class _Luid(ctypes.Structure):
    _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", ctypes.c_long)]


class _Rational(ctypes.Structure):
    _fields_ = [("Numerator", wintypes.UINT), ("Denominator", wintypes.UINT)]


class _PathSourceInfo(ctypes.Structure):
    _fields_ = [
        ("adapterId", _Luid),
        ("id", wintypes.UINT),
        ("modeInfoIdx", wintypes.UINT),
        ("statusFlags", wintypes.UINT),
    ]


class _PathTargetInfo(ctypes.Structure):
    _fields_ = [
        ("adapterId", _Luid),
        ("id", wintypes.UINT),
        ("modeInfoIdx", wintypes.UINT),
        ("outputTechnology", wintypes.UINT),
        ("rotation", wintypes.UINT),
        ("scaling", wintypes.UINT),
        ("refreshRate", _Rational),
        ("scanLineOrdering", wintypes.UINT),
        ("targetAvailable", wintypes.BOOL),
        ("statusFlags", wintypes.UINT),
    ]


class _PathInfo(ctypes.Structure):
    _fields_ = [
        ("sourceInfo", _PathSourceInfo),
        ("targetInfo", _PathTargetInfo),
        ("flags", wintypes.UINT),
    ]


class _DeviceInfoHeader(ctypes.Structure):
    _fields_ = [
        ("type", wintypes.UINT),
        ("size", wintypes.UINT),
        ("adapterId", _Luid),
        ("id", wintypes.UINT),
    ]


class _AdvancedColorInfo(ctypes.Structure):
    _fields_ = [
        ("header", _DeviceInfoHeader),
        ("value", wintypes.UINT),
        ("colorEncoding", wintypes.UINT),
        ("bitsPerColorChannel", wintypes.UINT),
    ]


class _AdvancedColorInfo2(ctypes.Structure):
    _fields_ = [
        ("header", _DeviceInfoHeader),
        ("value", wintypes.UINT),
        ("colorEncoding", wintypes.UINT),
        ("bitsPerColorChannel", wintypes.UINT),
        ("activeColorMode", wintypes.UINT),
    ]


@dataclass(frozen=True, slots=True)
class AdvancedColorStatus:
    """Aggregate capability for all active display targets."""

    supported: bool = False
    active: bool = False
    verified: bool = False
    reason_code: str = "capability_probe_unavailable"


class AdvancedColorProbe:
    """Read Advanced Color/HDR state through the supported DisplayConfig API."""

    def __init__(self, user32=None):
        self._user32 = user32 or ctypes.windll.user32

    def probe(self) -> AdvancedColorStatus:
        try:
            paths = self._active_paths()
        except (AttributeError, OSError, RuntimeError):
            return AdvancedColorStatus()
        if not paths:
            return AdvancedColorStatus(reason_code="no_active_display")

        supported = False
        active = False
        verified = True
        for path in paths:
            result = self._target_status(path.targetInfo)
            if result is None:
                verified = False
                continue
            target_supported, target_active = result
            supported = supported or target_supported
            active = active or target_active

        if active:
            return AdvancedColorStatus(
                supported=True,
                active=True,
                verified=verified,
                reason_code="hdr_active",
            )
        if not verified:
            return AdvancedColorStatus(
                supported=supported,
                active=False,
                verified=False,
                reason_code="capability_probe_unavailable",
            )
        return AdvancedColorStatus(
            supported=supported,
            active=False,
            verified=True,
            reason_code="sdr_ready",
        )

    def _active_paths(self) -> list[_PathInfo]:
        path_count = wintypes.UINT()
        mode_count = wintypes.UINT()
        get_sizes = self._user32.GetDisplayConfigBufferSizes
        query = self._user32.QueryDisplayConfig

        for _attempt in range(3):
            result = int(
                get_sizes(
                    QDC_ONLY_ACTIVE_PATHS,
                    ctypes.byref(path_count),
                    ctypes.byref(mode_count),
                )
            )
            if result != ERROR_SUCCESS:
                raise RuntimeError(f"GetDisplayConfigBufferSizes failed: {result}")
            if path_count.value == 0:
                return []

            path_array = (_PathInfo * path_count.value)()
            # The mode records are opaque here.  Reserve more than the SDK
            # structure size so Windows can populate the array safely.
            mode_buffer = ctypes.create_string_buffer(max(1, mode_count.value) * 128)
            result = int(
                query(
                    QDC_ONLY_ACTIVE_PATHS,
                    ctypes.byref(path_count),
                    path_array,
                    ctypes.byref(mode_count),
                    mode_buffer,
                    None,
                )
            )
            if result == ERROR_INSUFFICIENT_BUFFER:
                continue
            if result != ERROR_SUCCESS:
                raise RuntimeError(f"QueryDisplayConfig failed: {result}")
            return list(path_array[: path_count.value])
        raise RuntimeError("Display topology changed repeatedly during probing")

    def _target_status(self, target: _PathTargetInfo) -> tuple[bool, bool] | None:
        get_info = self._user32.DisplayConfigGetDeviceInfo

        info2 = _AdvancedColorInfo2()
        info2.header.type = DISPLAYCONFIG_GET_ADVANCED_COLOR_INFO_2
        info2.header.size = ctypes.sizeof(info2)
        info2.header.adapterId = target.adapterId
        info2.header.id = target.id
        if int(get_info(ctypes.byref(info2))) == ERROR_SUCCESS:
            supported = bool(info2.value & ((1 << 0) | (1 << 4)))
            active = info2.activeColorMode == DISPLAYCONFIG_ADVANCED_COLOR_MODE_HDR
            return supported, active

        info = _AdvancedColorInfo()
        info.header.type = DISPLAYCONFIG_GET_ADVANCED_COLOR_INFO
        info.header.size = ctypes.sizeof(info)
        info.header.adapterId = target.adapterId
        info.header.id = target.id
        if int(get_info(ctypes.byref(info))) != ERROR_SUCCESS:
            return None
        # The Windows 10 packet does not distinguish HDR from wide colour.
        # Suppressing Gamma for any active advanced-colour mode is the safe
        # aggregate behaviour.
        return bool(info.value & 1), bool(info.value & (1 << 1))


def probe_advanced_color() -> AdvancedColorStatus:
    """Convenience entry point used by the display service."""

    return AdvancedColorProbe().probe()
