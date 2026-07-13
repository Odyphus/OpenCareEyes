"""Blue light filter using Windows gamma ramp manipulation."""

import ctypes
import logging
from collections.abc import Callable

from opencareyes.core.color_temp import kelvin_to_rgb
from opencareyes.core.display_capabilities import (
    AdvancedColorStatus,
    probe_advanced_color,
)
from opencareyes.core.monitor_manager import MonitorManager
from opencareyes.platform.win32_api import (
    CreateDCW,
    DeleteDC,
    GetDeviceGammaRamp,
    SetDeviceGammaRamp,
    get_display_source_identity,
)

log = logging.getLogger(__name__)

# Gamma ramp: 256 entries per channel (R, G, B) = 768 total unsigned shorts
_RAMP_SIZE = 256
_GammaArray = ctypes.c_ushort * (_RAMP_SIZE * 3)
_OutputIdentity = tuple[str, tuple[str, ...]]


class BlueLightFilter:
    """Adjusts screen color temperature by manipulating the display gamma ramp."""

    def __init__(
        self,
        monitor_manager: MonitorManager | None = None,
        hdr_probe: Callable[[], AdvancedColorStatus] | None = None,
        identity_resolver: Callable[[str], tuple[str, ...]] | None = None,
        *,
        connect_screen_events: bool = True,
    ):
        self._monitor_manager = monitor_manager or MonitorManager()
        self._hdr_probe = hdr_probe or probe_advanced_color
        self._identity_resolver = (
            identity_resolver or get_display_source_identity
        )
        self._original_ramps: dict[_OutputIdentity, _GammaArray] = {}
        self._current_temp: int = 6500
        self._enabled: bool = False
        self._capability = AdvancedColorStatus()
        self._last_error_code = ""
        self._last_error_message = ""
        try:
            from PySide6.QtWidgets import QApplication

            app = QApplication.instance()
            if connect_screen_events and app is not None:
                app.screenAdded.connect(self.refresh_screens)
                app.screenRemoved.connect(self.refresh_screens)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def enable(self, temperature: int = 4500) -> bool:
        """Enable the blue light filter at the given color temperature."""
        capability = self.probe_capability()
        if capability.active:
            self._suppress_for_hdr()
            return False
        if not self._enabled and not self._original_ramps:
            if not self._capture_original_ramps():
                if self._last_error_code not in {
                    "display_identity_unavailable",
                    "gamma_open_failed",
                }:
                    self._last_error_code = "gamma_capture_failed"
                    self._last_error_message = (
                        "无法读取原始显示色彩，未应用色温。"
                    )
                self._original_ramps.clear()
                return False
        applied = self._apply_temperature_after_probe(temperature)
        self._enabled = applied
        if applied:
            self._last_error_code = ""
            self._last_error_message = ""
            log.info("Blue light filter enabled at %dK", temperature)
        return applied

    def disable(self) -> bool:
        """Disable the filter and restore the original gamma ramp."""
        if self.probe_capability().active:
            self._suppress_for_hdr()
            return True
        restored = True
        if self._original_ramps:
            restored = self._restore_original_ramps()
        self._enabled = False
        self._current_temp = 6500
        if restored:
            self._last_error_code = ""
            self._last_error_message = ""
        elif self._last_error_code != "hdr_active":
            self._set_rollback_failed()
        log.info("Blue light filter disabled")
        return restored or self._last_error_code == "hdr_active"

    def set_temperature(self, kelvin: int) -> bool:
        """Apply a color temperature to all monitors."""
        if self.probe_capability().active:
            self._suppress_for_hdr()
            return False
        return self._apply_temperature_after_probe(kelvin)

    def _apply_temperature_after_probe(self, kelvin: int) -> bool:
        """Write Gamma after the caller has performed one fresh HDR probe."""

        r, g, b = kelvin_to_rgb(kelvin)
        ramp = self._build_gamma_ramp(r, g, b)
        applied = self._apply_ramp(ramp)
        if applied:
            self._current_temp = kelvin
            self._last_error_code = ""
            self._last_error_message = ""
        else:
            self._enabled = False
            self._current_temp = 6500
            if self._last_error_code not in {
                "display_identity_unavailable",
                "gamma_baseline_unavailable",
                "gamma_open_failed",
                "gamma_rollback_failed",
                "hdr_active",
            }:
                self._last_error_code = "gamma_apply_failed"
                self._last_error_message = (
                    "色温未能在所有活动显示输出上生效，已恢复原始色彩。"
                )
        return applied

    def refresh_screens(self, *_) -> bool:
        """Capture newly attached displays and reapply the active filter."""
        self._monitor_manager.refresh()
        capability = self.probe_capability()
        if capability.active:
            self._suppress_for_hdr()
            return True
        if self._last_error_code == "hdr_active":
            self._last_error_code = ""
            self._last_error_message = ""
        if not self._enabled:
            return True
        if not self._capture_original_ramps(overwrite=False):
            restored = self._restore_original_ramps()
            self._enabled = False
            self._current_temp = 6500
            if restored:
                self._last_error_code = "gamma_capture_failed"
                self._last_error_message = (
                    "显示配置变化后无法读取原始色彩，已停止色温调节。"
                )
            elif self._last_error_code != "hdr_active":
                self._set_rollback_failed()
            return self._last_error_code == "hdr_active"
        applied = self._apply_temperature_after_probe(self._current_temp)
        return applied or self._last_error_code == "hdr_active"

    def _suppress_for_hdr(self) -> None:
        """Mark Gamma inactive without attempting undefined HDR writes."""

        self._enabled = False
        self._current_temp = 6500
        self._original_ramps.clear()
        self._last_error_code = "hdr_active"
        self._last_error_message = "HDR 已开启，色温调节已安全暂停。"

    def probe_capability(self) -> AdvancedColorStatus:
        """Refresh the aggregate HDR/Advanced Color state."""

        try:
            self._capability = self._hdr_probe()
        except Exception:
            log.exception("Advanced Color capability probe failed")
            self._capability = AdvancedColorStatus()
        return self._capability

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------
    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def current_temperature(self) -> int:
        return self._current_temp

    @property
    def capability(self) -> AdvancedColorStatus:
        return self._capability

    @property
    def hdr_active(self) -> bool:
        return self._capability.active

    @property
    def capability_verified(self) -> bool:
        return self._capability.verified

    @property
    def last_error_code(self) -> str:
        return self._last_error_code

    @property
    def last_error_message(self) -> str:
        return self._last_error_message

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

    def _capture_original_ramps(self, overwrite: bool = True) -> bool:
        """Capture each display's gamma ramp before changing it."""
        entries = self._open_display_dcs()
        if not entries:
            return False
        updated = dict(self._original_ramps)
        success = True
        for identity, dc, release_kind in entries:
            try:
                matched = self._matching_baseline(identity, updated)
                if not overwrite and matched is not None:
                    if matched != identity:
                        updated[identity] = updated.pop(matched)
                    continue
                ramp = _GammaArray()
                if GetDeviceGammaRamp(dc, ctypes.byref(ramp)):
                    source = identity[0]
                    for previous in tuple(updated):
                        if previous[0] == source:
                            updated.pop(previous)
                    updated[identity] = ramp
                else:
                    log.warning(
                        "GetDeviceGammaRamp failed for %s",
                        identity[0],
                    )
                    success = False
            finally:
                self._release_dc(dc, release_kind)
        if success:
            self._original_ramps = updated
        return success

    def _restore_original_ramps(self) -> bool:
        """Restore original ramps for all displays that are still attached."""
        entries = self._open_display_dcs()
        if not entries:
            return False
        migrated = dict(self._original_ramps)
        for identity, _dc, _release_kind in entries:
            matched = self._matching_baseline(identity, migrated)
            if matched is None:
                self._release_entries(entries)
                self._last_error_code = "gamma_baseline_unavailable"
                self._last_error_message = (
                    "显示器连接已变化且缺少可信原始色彩快照，未执行色温操作。"
                )
                return False
            if matched != identity:
                migrated[identity] = migrated.pop(matched)
        if self.probe_capability().active:
            self._release_entries(entries)
            self._suppress_for_hdr()
            return False

        success = True
        for identity, dc, release_kind in entries:
            try:
                ramp = migrated[identity]
                if not SetDeviceGammaRamp(dc, ctypes.byref(ramp)):
                    log.warning(
                        "SetDeviceGammaRamp restore failed for %s",
                        identity[0],
                    )
                    success = False
            finally:
                self._release_dc(dc, release_kind)
        if success:
            self._original_ramps.clear()
        else:
            self._original_ramps = migrated
        return success

    def _apply_ramp(self, ramp: _GammaArray) -> bool:
        """Apply a gamma ramp to every attached display."""
        entries = self._open_display_dcs()
        if not entries:
            return False

        migrated = dict(self._original_ramps)
        for identity, _dc, _release_kind in entries:
            matched = self._matching_baseline(identity, migrated)
            if matched is None:
                for _unused, dc, release_kind in entries:
                    self._release_dc(dc, release_kind)
                self._last_error_code = "gamma_baseline_unavailable"
                self._last_error_message = (
                    "显示器连接已变化且缺少可信原始色彩快照，未执行色温操作。"
                )
                return False
            if matched != identity:
                migrated[identity] = migrated.pop(matched)
        self._original_ramps = migrated
        if self.probe_capability().active:
            self._release_entries(entries)
            self._suppress_for_hdr()
            return False

        success = True
        for identity, dc, release_kind in entries:
            try:
                if not SetDeviceGammaRamp(dc, ctypes.byref(ramp)):
                    log.warning(
                        "SetDeviceGammaRamp failed for %s",
                        identity[0],
                    )
                    success = False
                    continue
                readback = _GammaArray()
                if not GetDeviceGammaRamp(dc, ctypes.byref(readback)):
                    log.warning(
                        "GetDeviceGammaRamp verification failed for %s",
                        identity[0],
                    )
                    success = False
                    continue
                if bytes(readback) != bytes(ramp):
                    log.warning(
                        "Gamma ramp verification mismatch for %s",
                        identity[0],
                    )
                    success = False
            finally:
                self._release_dc(dc, release_kind)

        if not success and not self._restore_original_ramps():
            if self._last_error_code != "hdr_active":
                self._set_rollback_failed()
        return success

    def _set_rollback_failed(self) -> None:
        """Expose an incomplete rollback while retaining its retry baseline."""

        self._last_error_code = "gamma_rollback_failed"
        self._last_error_message = (
            "显示色彩恢复不完整；已保留原始色彩快照，请重试关闭屏幕效果。"
        )

    def _open_display_dcs(self):
        """Open every display only after all stable identities are known."""

        try:
            monitors = self._monitor_manager.get_monitors()
        except Exception:
            log.exception("Failed to enumerate display sources")
            self._set_identity_unavailable()
            return []
        if not monitors:
            self._set_identity_unavailable()
            return []

        resolved: list[tuple[_OutputIdentity, str]] = []
        sources: set[str] = set()
        targets: set[str] = set()
        try:
            for monitor in monitors:
                name = str(monitor["name"]).strip()
                source = name.casefold()
                identities = tuple(
                    str(value).strip().casefold()
                    for value in self._identity_resolver(name)
                )
                if (
                    not source
                    or source in sources
                    or not identities
                    or any(not value for value in identities)
                    or len(set(identities)) != len(identities)
                    or any(value in targets for value in identities)
                ):
                    raise OSError("ambiguous display identity")
                sources.add(source)
                targets.update(identities)
                resolved.append(((source, tuple(sorted(identities))), name))
        except Exception:
            log.exception("Failed to resolve stable display identities")
            self._set_identity_unavailable()
            return []

        entries = []
        for identity, name in resolved:
            dc = CreateDCW("DISPLAY", name, None, None)
            if not dc:
                for _identity, opened, release_kind in entries:
                    self._release_dc(opened, release_kind)
                self._last_error_code = "gamma_open_failed"
                self._last_error_message = (
                    "无法打开全部活动显示输出，未执行屏幕色温操作。"
                )
                return []
            entries.append((identity, dc, "delete"))
        return entries

    @staticmethod
    def _matching_baseline(
        identity: _OutputIdentity,
        baselines: dict[_OutputIdentity, _GammaArray],
    ) -> _OutputIdentity | None:
        if identity in baselines:
            return identity
        source, target_ids = identity
        targets = set(target_ids)
        matches = [
            previous
            for previous in baselines
            if previous[0] == source and targets.intersection(previous[1])
        ]
        return matches[0] if len(matches) == 1 else None

    def _set_identity_unavailable(self) -> None:
        self._last_error_code = "display_identity_unavailable"
        self._last_error_message = (
            "无法可靠识别当前显示器，已安全停止色温操作；请重试或重新连接显示器。"
        )

    def _release_entries(self, entries) -> None:
        for _identity, dc, release_kind in entries:
            self._release_dc(dc, release_kind)

    @staticmethod
    def _release_dc(dc, release_kind: str):
        del release_kind
        DeleteDC(dc)
