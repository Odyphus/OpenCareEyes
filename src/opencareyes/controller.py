"""Single write entry point for OpenCareEyes application state."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from PySide6.QtCore import QObject, QTimer, Signal

from opencareyes.constants import (
    DIM_MAX,
    DIM_MIN,
    HOTKEY_TOGGLE_BREAK,
    HOTKEY_TOGGLE_DIMMER,
    HOTKEY_TOGGLE_FILTER,
    HOTKEY_TOGGLE_FOCUS,
    TEMP_MAX,
    TEMP_MIN,
)
from opencareyes.diagnostics import export_diagnostics as write_diagnostics
from opencareyes.state import (
    AppState,
    AutomationState,
    BreakState,
    CapabilitiesState,
    DisplayState,
    FocusState,
    GeneralState,
    GlobalPauseState,
    HotkeyState,
)

if TYPE_CHECKING:
    from opencareyes.config.settings import Settings
    from opencareyes.core.break_reminder import BreakReminder
    from opencareyes.core.scheduler import Scheduler
    from opencareyes.platform.hotkeys import HotkeyManager

log = logging.getLogger(__name__)


class AppController(QObject):
    """Own all feature mutations and publish immutable snapshots."""

    state_changed = Signal(object)
    operation_failed = Signal(str, str)
    notification_requested = Signal(str, str)

    def __init__(
        self,
        settings: Settings,
        blue_filter=None,
        dimmer=None,
        break_reminder: BreakReminder | None = None,
        focus_mode=None,
        scheduler: Scheduler | None = None,
        hotkeys: HotkeyManager | None = None,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self._settings = settings
        self._blue_filter = blue_filter
        self._dimmer = dimmer
        self._break_reminder = break_reminder
        self._focus_mode = focus_mode
        self._scheduler = scheduler
        self._hotkeys = hotkeys
        self._restored = False

        self._pause_timer = QTimer(self)
        self._pause_timer.setSingleShot(True)
        self._pause_timer.timeout.connect(self.resume_all)
        self._focus_timer = QTimer(self)
        self._focus_timer.setSingleShot(True)
        self._focus_timer.timeout.connect(self._on_focus_session_timeout)
        self._focus_session_ends_at: datetime | None = None

        if self._break_reminder is not None:
            if hasattr(self._break_reminder, "state_changed"):
                self._break_reminder.state_changed.connect(self.refresh_state)
            self._break_reminder.break_started.connect(
                lambda: self.notification_requested.emit(
                    "休息时间", "看看远处，让眼睛放松一下。"
                )
            )

        if self._scheduler is not None:
            self._scheduler.set_state_callback(
                self._on_scheduled_filter_state_requested
            )
            self._scheduler.next_event_changed.connect(self.refresh_state)
            self._scheduler.running_changed.connect(self.refresh_state)
            self._scheduler.manual_override_changed.connect(self.refresh_state)
            self._scheduler.error.connect(self.operation_failed)

        if self._hotkeys is not None:
            self._hotkeys.registration_failed.connect(self.operation_failed)
            self._hotkeys.callback_failed.connect(self.operation_failed)

        self._state = self._build_state()

    @property
    def state(self) -> AppState:
        return self._state

    @property
    def settings(self) -> Settings:
        return self._settings

    def restore(self) -> bool:
        """Apply persisted configuration to services once at startup."""
        success = True
        try:
            if self._break_reminder is not None:
                self._break_reminder.set_mode(self._settings.break_mode)
                self._break_reminder.set_work_duration(self._settings.work_duration)
                self._break_reminder.set_break_duration(
                    self._settings.break_duration
                )
                self._break_reminder.force_break = self._settings.force_break
            if self._focus_mode is not None:
                self._focus_mode.set_dim_level(self._settings.focus_dim_level)
        except Exception as exc:
            success = False
            self._fail("restore_configuration", exc)

        pause_active = self._restore_pause_deadline()
        if not pause_active:
            success = self._restore_configured_services() and success
        else:
            success = self._disable_effects_for_pause() and success

        if self._scheduler is not None:
            try:
                if self._settings.filter_schedule_enabled:
                    self._scheduler.start()
                else:
                    self._scheduler.stop()
            except Exception as exc:
                success = False
                self._fail("restore_schedule", exc)

        if self._hotkeys is not None:
            success = self._register_hotkeys() and success

        self._restored = True
        self.refresh_state()
        return success

    def refresh_state(self, *_args, force: bool = False) -> AppState:
        new_state = self._build_state()
        if force or new_state != self._state:
            self._state = new_state
            self.state_changed.emit(new_state)
        return self._state

    # ---- Feature switches ----

    def set_feature_enabled(self, feature: str, enabled: bool) -> bool:
        handlers = {
            "filter": self.set_filter_enabled,
            "dimmer": self.set_dimmer_enabled,
            "break": self.set_break_enabled,
            "breaks": self.set_break_enabled,
            "focus": self.set_focus_enabled,
            "schedule": lambda value: self.set_schedule(value),
            "automation": lambda value: self.set_schedule(value),
        }
        handler = handlers.get(feature.strip().lower())
        if handler is None:
            self.operation_failed.emit("unknown_feature", feature)
            return False
        return handler(bool(enabled))

    def set_filter_enabled(self, enabled: bool) -> bool:
        enabled = bool(enabled)

        def operation() -> None:
            if not self._is_globally_paused():
                self._set_service_enabled(
                    self._blue_filter,
                    enabled,
                    lambda: self._blue_filter.enable(
                        self._settings.color_temperature
                    ),
                )
            self._settings.filter_enabled = enabled
            if self._scheduler is not None and self._scheduler.running:
                self._scheduler.set_manual_override(True)

        return self._run("filter_toggle", operation)

    def set_dimmer_enabled(self, enabled: bool) -> bool:
        enabled = bool(enabled)

        def operation() -> None:
            if not self._is_globally_paused():
                self._set_service_enabled(
                    self._dimmer,
                    enabled,
                    lambda: self._dimmer.enable(self._settings.dim_level),
                )
            self._settings.dimmer_enabled = enabled

        return self._run("dimmer_toggle", operation)

    def set_break_enabled(self, enabled: bool) -> bool:
        enabled = bool(enabled)

        def operation() -> None:
            self._require_service(self._break_reminder, "break reminder")
            if enabled and not self._is_globally_paused():
                self._break_reminder.start()
            elif not enabled:
                self._break_reminder.stop()
            self._settings.break_enabled = enabled

        return self._run("break_toggle", operation)

    def set_focus_enabled(self, enabled: bool) -> bool:
        enabled = bool(enabled)

        def operation() -> None:
            if not self._is_globally_paused():
                self._set_service_enabled(
                    self._focus_mode, enabled, self._focus_mode.enable
                )
            elif not enabled and self._focus_mode is not None:
                self._focus_mode.disable()
            self._settings.focus_enabled = enabled
            if not enabled:
                self._focus_timer.stop()
                self._focus_session_ends_at = None

        return self._run("focus_toggle", operation)

    # ---- Display and break configuration ----

    def set_color_temperature(self, kelvin: int, persist: bool = True) -> bool:
        kelvin = max(TEMP_MIN, min(TEMP_MAX, int(kelvin)))

        def operation() -> None:
            if (
                self._settings.filter_enabled
                and not self._is_globally_paused()
            ):
                self._require_service(self._blue_filter, "blue-light filter")
                self._blue_filter.set_temperature(kelvin)
            if persist:
                self._settings.color_temperature = kelvin
                self._settings.current_preset = "custom"

        return self._run("filter_temperature", operation)

    def set_dim_level(self, level: int, persist: bool = True) -> bool:
        level = max(DIM_MIN, min(DIM_MAX, int(level)))

        def operation() -> None:
            if self._settings.dimmer_enabled and not self._is_globally_paused():
                self._require_service(self._dimmer, "screen dimmer")
                self._dimmer.set_brightness(level)
            if persist:
                self._settings.dim_level = level
                self._settings.current_preset = "custom"

        return self._run("dimmer_level", operation)

    def set_focus_dim_level(self, level: int) -> bool:
        level = max(0, min(255, int(level)))

        def operation() -> None:
            self._require_service(self._focus_mode, "focus mode")
            self._focus_mode.set_dim_level(level)
            self._settings.focus_dim_level = level

        return self._run("focus_dim_level", operation)

    def set_break_mode(self, mode: str) -> bool:
        def operation() -> None:
            self._require_service(self._break_reminder, "break reminder")
            self._break_reminder.set_mode(mode)
            self._settings.break_mode = mode
            self._settings.work_duration = self._break_reminder.work_duration
            self._settings.break_duration = self._break_reminder.break_duration
            if self._settings.break_enabled and not self._is_globally_paused():
                self._break_reminder.start()

        return self._run("break_mode", operation)

    def set_break_durations(self, work_seconds: int, break_seconds: int) -> bool:
        work_seconds = max(1, int(work_seconds))
        break_seconds = max(1, int(break_seconds))

        def operation() -> None:
            self._require_service(self._break_reminder, "break reminder")
            self._break_reminder.set_mode("custom")
            self._break_reminder.set_work_duration(work_seconds)
            self._break_reminder.set_break_duration(break_seconds)
            self._settings.break_mode = "custom"
            self._settings.work_duration = work_seconds
            self._settings.break_duration = break_seconds
            if self._settings.break_enabled and not self._is_globally_paused():
                self._break_reminder.start()

        return self._run("break_duration", operation)

    def set_force_break(self, enabled: bool) -> bool:
        def operation() -> None:
            self._require_service(self._break_reminder, "break reminder")
            self._break_reminder.force_break = bool(enabled)
            self._settings.force_break = bool(enabled)

        return self._run("force_break", operation)

    def set_break_countdown_display(self, mode: str) -> bool:
        if mode not in {"floating", "tray", "hidden"}:
            self.operation_failed.emit("break_display", f"Unknown display mode: {mode}")
            return False
        return self._run(
            "break_display",
            lambda: setattr(self._settings, "break_countdown_display", mode),
        )

    def pause_break(self) -> bool:
        return self._run(
            "break_pause",
            lambda: self._require_and_call(self._break_reminder, "pause"),
        )

    def resume_break(self) -> bool:
        return self._run(
            "break_resume",
            lambda: self._require_and_call(self._break_reminder, "resume"),
        )

    def snooze_break(self, minutes: int = 5) -> bool:
        minutes = max(1, int(minutes))

        def operation() -> None:
            self._require_service(self._break_reminder, "break reminder")
            if self._break_reminder.force_break:
                raise ValueError("严格休息模式下不能稍后提醒")
            self._break_reminder.snooze(minutes * 60)

        return self._run(
            "break_snooze",
            operation,
        )

    def skip_break(self) -> bool:
        return self._run(
            "break_skip",
            lambda: self._require_and_call(self._break_reminder, "skip_break"),
        )

    def apply_display_profile(
        self,
        name: str,
        *,
        mark_manual_override: bool = True,
    ) -> bool:
        try:
            from opencareyes.config.presets import PRESETS

            preset = PRESETS[name]
        except (KeyError, ImportError, SyntaxError) as exc:
            self._fail("unknown_display_profile", exc)
            return False

        temperature = max(TEMP_MIN, min(TEMP_MAX, int(preset["temp"])))
        dim_level = max(DIM_MIN, min(DIM_MAX, int(preset["dim"])))

        def operation() -> None:
            if not self._is_globally_paused():
                self._require_service(self._blue_filter, "blue-light filter")
                self._blue_filter.enable(temperature)
                if dim_level > 0:
                    self._require_service(self._dimmer, "screen dimmer")
                    self._dimmer.enable(dim_level)
                elif self._dimmer is not None:
                    self._dimmer.disable()
            self._settings.color_temperature = temperature
            self._settings.dim_level = dim_level
            self._settings.filter_enabled = True
            self._settings.dimmer_enabled = dim_level > 0
            self._settings.current_preset = name
            if (
                mark_manual_override
                and self._scheduler is not None
                and self._scheduler.running
            ):
                self._scheduler.set_manual_override(True)

        return self._run("display_profile", operation)

    # ---- Automation and temporary pause ----

    def set_schedule(
        self,
        enabled: bool,
        *,
        mode: str | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
        on_time: str | None = None,
        off_time: str | None = None,
        days=None,
    ) -> bool:
        enabled = bool(enabled)
        selected_mode = mode or self._settings.schedule_mode
        if selected_mode not in {"sun", "fixed"}:
            self.operation_failed.emit(
                "schedule_mode", f"Unknown schedule mode: {selected_mode}"
            )
            return False
        if (latitude is None) != (longitude is None):
            self.operation_failed.emit(
                "schedule_location", "Latitude and longitude are both required"
            )
            return False
        if latitude is not None and not (-90 <= float(latitude) <= 90):
            self.operation_failed.emit("schedule_location", "Invalid latitude")
            return False
        if longitude is not None and not (-180 <= float(longitude) <= 180):
            self.operation_failed.emit("schedule_location", "Invalid longitude")
            return False
        if on_time is not None and not self._valid_clock_time(on_time):
            self.operation_failed.emit("schedule_time", "Invalid on time")
            return False
        if off_time is not None and not self._valid_clock_time(off_time):
            self.operation_failed.emit("schedule_time", "Invalid off time")
            return False
        selected_days = None if days is None else tuple(sorted(set(days)))
        if selected_days is not None and (
            not selected_days
            or any(not isinstance(day, int) or day < 0 or day > 6 for day in selected_days)
        ):
            self.operation_failed.emit("schedule_days", "Invalid workday selection")
            return False
        location_configured = self._settings.location_configured or latitude is not None
        if enabled and selected_mode == "sun" and not location_configured:
            self.operation_failed.emit(
                "schedule_location", "Please choose a location first"
            )
            return False

        def operation() -> None:
            self._require_service(self._scheduler, "scheduler")
            self._settings.schedule_mode = selected_mode
            if latitude is not None:
                self._settings.latitude = float(latitude)
                self._settings.longitude = float(longitude)
                self._settings.location_configured = True
            if on_time is not None:
                self._settings.schedule_on_time = on_time
            if off_time is not None:
                self._settings.schedule_off_time = off_time
            if selected_days is not None:
                self._settings.schedule_days = selected_days
            self._settings.filter_schedule_enabled = enabled
            if enabled:
                self._scheduler.start()
            else:
                self._scheduler.stop()

        return self._run("schedule", operation)

    def pause_all(
        self,
        minutes: int | None = None,
        *,
        until_next_schedule: bool = False,
    ) -> bool:
        if minutes is not None and until_next_schedule:
            self.operation_failed.emit(
                "global_pause", "Choose a duration or the next schedule event"
            )
            return False
        if minutes is not None and int(minutes) <= 0:
            self.operation_failed.emit("global_pause", "Duration must be positive")
            return False
        if until_next_schedule and (
            self._scheduler is None or not self._scheduler.running
        ):
            self.operation_failed.emit(
                "global_pause", "Automation is not running"
            )
            return False

        mode = "next_schedule" if until_next_schedule else (
            "timed" if minutes is not None else "manual"
        )
        until_timestamp: float | None = None
        if minutes is not None:
            until_timestamp = time.time() + int(minutes) * 60

        def operation() -> None:
            self._settings.global_pause_mode = mode
            self._settings.global_pause_until = until_timestamp
            self._pause_timer.stop()
            if minutes is not None:
                self._pause_timer.start(min(int(minutes) * 60_000, 2_147_483_647))
            self._disable_effects_for_pause(raise_errors=True)

        return self._run("global_pause", operation)

    def resume_all(self) -> bool:
        def operation() -> None:
            self._pause_timer.stop()
            self._settings.global_pause_mode = "none"
            self._settings.global_pause_until = None
            if self._restored:
                if not self._restore_configured_services(raise_errors=True):
                    raise RuntimeError("One or more effects could not be restored")

        return self._run("global_resume", operation)

    # ---- Focus session and general settings ----

    def start_focus_session(self, minutes: int) -> bool:
        minutes = int(minutes)
        if minutes <= 0:
            self.operation_failed.emit("focus_session", "Duration must be positive")
            return False
        if not self.set_focus_enabled(True):
            return False
        self._focus_session_ends_at = datetime.now().astimezone() + timedelta(
            minutes=minutes
        )
        self._focus_timer.start(min(minutes * 60_000, 2_147_483_647))
        self.refresh_state()
        return True

    def set_theme(self, theme: str) -> bool:
        if theme not in {"system", "light", "dark"}:
            self.operation_failed.emit("theme", f"Unknown theme: {theme}")
            return False
        return self._run("theme", lambda: setattr(self._settings, "theme", theme))

    def set_autostart(self, enabled: bool) -> bool:
        enabled = bool(enabled)

        def operation() -> None:
            from opencareyes.platform.autostart import (
                disable_autostart,
                enable_autostart,
            )

            if enabled:
                enable_autostart()
            else:
                disable_autostart()
            self._settings.autostart = enabled

        return self._run("autostart", operation)

    def set_location(
        self, latitude: float, longitude: float, city: str = ""
    ) -> bool:
        latitude = float(latitude)
        longitude = float(longitude)
        if not (-90 <= latitude <= 90) or not (-180 <= longitude <= 180):
            self.operation_failed.emit("location", "Invalid latitude or longitude")
            return False

        def operation() -> None:
            self._settings.latitude = latitude
            self._settings.longitude = longitude
            self._settings.city = city.strip()
            self._settings.location_configured = True
            if self._scheduler is not None and self._scheduler.running:
                self._scheduler.reschedule()

        return self._run("location", operation)

    def set_hotkey(self, action: str, sequence: str) -> bool:
        action = action.strip().lower()
        if action == "breaks":
            action = "break"
        properties = {
            "filter": "hotkey_filter",
            "break": "hotkey_break",
            "dimmer": "hotkey_dimmer",
            "focus": "hotkey_focus",
        }
        property_name = properties.get(action)
        sequence = sequence.strip().lower()
        if property_name is None or not sequence:
            self.operation_failed.emit("hotkey", "Unknown action or empty hotkey")
            return False
        for other_action, other_property in properties.items():
            if other_action != action and getattr(self._settings, other_property).lower() == sequence:
                self.operation_failed.emit(
                    "hotkey_conflict", f"{sequence} is already in use"
                )
                return False

        old_sequence = getattr(self._settings, property_name)
        callback = self._hotkey_callbacks()[action]

        def operation() -> None:
            if self._hotkeys is not None:
                self._hotkeys.unregister(old_sequence)
                if not self._hotkeys.register(sequence, callback):
                    self._hotkeys.register(old_sequence, callback)
                    raise RuntimeError(f"Could not register {sequence}")
            setattr(self._settings, property_name, sequence)

        return self._run("hotkey", operation)

    def reset_hotkeys(self) -> bool:
        defaults = {
            "filter": HOTKEY_TOGGLE_FILTER,
            "break": HOTKEY_TOGGLE_BREAK,
            "dimmer": HOTKEY_TOGGLE_DIMMER,
            "focus": HOTKEY_TOGGLE_FOCUS,
        }
        success = True
        for action, sequence in defaults.items():
            success = self.set_hotkey(action, sequence) and success
        return success

    def complete_onboarding(self) -> bool:
        return self._run(
            "onboarding",
            lambda: setattr(self._settings, "onboarding_completed", True),
        )

    def mark_onboarding_complete(self) -> bool:
        return self.complete_onboarding()

    def export_diagnostics(self, path: str | Path) -> bool:
        destination = Path(path)
        state = self.refresh_state()
        return self._run(
            "diagnostics_export",
            lambda: write_diagnostics(destination, state),
        )

    def reset_settings(self) -> bool:
        def operation() -> None:
            self._pause_timer.stop()
            self._focus_timer.stop()
            self._focus_session_ends_at = None
            if self._scheduler is not None:
                self._scheduler.stop()
            if self._hotkeys is not None:
                self._hotkeys.unregister_all()
            for service in (
                self._break_reminder,
                self._focus_mode,
                self._dimmer,
                self._blue_filter,
            ):
                if service is not None:
                    stop = getattr(service, "stop", None) or getattr(
                        service, "disable", None
                    )
                    if stop is not None:
                        stop()
            self._settings.reset()
            self._restored = False

        return self._run("settings_reset", operation)

    # ---- Internal service orchestration ----

    def _on_scheduled_filter_state_requested(self, enabled: bool) -> None:
        if (
            self._is_globally_paused()
            and self._settings.global_pause_mode == "next_schedule"
        ):
            self._settings.global_pause_mode = "none"
            self._settings.global_pause_until = None
            self._pause_timer.stop()
            self._restore_configured_services()

        profile = "night" if enabled else "office"
        self.apply_display_profile(profile, mark_manual_override=False)

    def _restore_configured_services(self, raise_errors: bool = False) -> bool:
        success = True
        operations: list[tuple[str, str, Callable[[], None]]] = [
            (
                "restore_filter",
                "filter_enabled",
                lambda: self._set_service_enabled(
                    self._blue_filter,
                    self._settings.filter_enabled,
                    lambda: self._blue_filter.enable(
                        self._settings.color_temperature
                    ),
                ),
            ),
            (
                "restore_dimmer",
                "dimmer_enabled",
                lambda: self._set_service_enabled(
                    self._dimmer,
                    self._settings.dimmer_enabled,
                    lambda: self._dimmer.enable(self._settings.dim_level),
                ),
            ),
            (
                "restore_break",
                "break_enabled",
                lambda: self._restore_break_service(),
            ),
            (
                "restore_focus",
                "focus_enabled",
                lambda: self._set_service_enabled(
                    self._focus_mode,
                    self._settings.focus_enabled,
                    self._focus_mode.enable if self._focus_mode is not None else None,
                ),
            ),
        ]
        for code, setting_name, operation in operations:
            try:
                operation()
            except Exception as exc:
                success = False
                if getattr(self._settings, setting_name):
                    setattr(self._settings, setting_name, False)
                    self._settings.sync()
                self._fail(code, exc)
                if raise_errors:
                    raise
        return success

    def _restore_break_service(self) -> None:
        if self._break_reminder is None:
            if self._settings.break_enabled:
                raise RuntimeError("Break reminder is unavailable")
            return
        if self._settings.break_enabled:
            if self._break_reminder.enabled and self._break_reminder.paused:
                self._break_reminder.resume()
            elif not self._break_reminder.enabled:
                self._break_reminder.start()
        else:
            self._break_reminder.stop()

    def _disable_effects_for_pause(self, raise_errors: bool = False) -> bool:
        success = True
        for code, service in (
            ("pause_filter", self._blue_filter),
            ("pause_dimmer", self._dimmer),
            ("pause_break", self._break_reminder),
            ("pause_focus", self._focus_mode),
        ):
            if service is None:
                continue
            method = getattr(service, "stop", None) or getattr(
                service, "disable", None
            )
            if method is None:
                continue
            try:
                method()
            except Exception as exc:
                success = False
                self._fail(code, exc)
                if raise_errors:
                    raise
        return success

    def _set_service_enabled(
        self,
        service,
        enabled: bool,
        enable: Callable[[], None] | None,
    ) -> None:
        if service is None:
            if enabled:
                raise RuntimeError("Required service is unavailable")
            return
        if enabled:
            if enable is None:
                raise RuntimeError("Service cannot be enabled")
            enable()
        else:
            service.disable()
        actual = getattr(service, "enabled", None)
        if isinstance(actual, bool) and actual != enabled:
            raise RuntimeError("Service did not enter the requested state")

    @staticmethod
    def _require_service(service, name: str) -> None:
        if service is None:
            raise RuntimeError(f"{name} is unavailable")

    @classmethod
    def _require_and_call(cls, service, method: str, *args) -> None:
        cls._require_service(service, method)
        getattr(service, method)(*args)

    def _run(self, code: str, operation: Callable[[], object]) -> bool:
        try:
            operation()
            self._settings.sync()
        except Exception as exc:
            self._fail(code, exc)
            # Republish even when persistence is unchanged so controls that
            # optimistically toggled themselves are restored in this event loop.
            self.refresh_state(force=True)
            return False
        self.refresh_state()
        return True

    def _fail(self, code: str, error: Exception | str) -> None:
        message = str(error) or error.__class__.__name__
        log.error("Operation failed [%s]: %s", code, message)
        self.operation_failed.emit(code, message)

    def _restore_pause_deadline(self) -> bool:
        mode = self._settings.global_pause_mode
        until = self._settings.global_pause_until
        if mode == "timed":
            if until is None or until <= time.time():
                self._settings.global_pause_mode = "none"
                self._settings.global_pause_until = None
                return False
            milliseconds = max(1, int((until - time.time()) * 1000))
            self._pause_timer.start(min(milliseconds, 2_147_483_647))
            return True
        if mode in {"manual", "next_schedule"}:
            return True
        if mode != "none":
            self._settings.global_pause_mode = "none"
            self._settings.global_pause_until = None
        return False

    def _is_globally_paused(self) -> bool:
        mode = self._settings.global_pause_mode
        if mode != "timed":
            return mode in {"manual", "next_schedule"}
        until = self._settings.global_pause_until
        return until is not None and until > time.time()

    def _on_focus_session_timeout(self) -> None:
        self._focus_session_ends_at = None
        self.set_focus_enabled(False)

    def _register_hotkeys(self) -> bool:
        if self._hotkeys is None:
            return True
        self._hotkeys.unregister_all()
        callbacks = self._hotkey_callbacks()
        success = True
        for action, sequence in (
            ("filter", self._settings.hotkey_filter),
            ("break", self._settings.hotkey_break),
            ("dimmer", self._settings.hotkey_dimmer),
            ("focus", self._settings.hotkey_focus),
        ):
            if not self._hotkeys.register(sequence, callbacks[action]):
                success = False
        return success

    def _hotkey_callbacks(self) -> dict[str, Callable[[], bool]]:
        return {
            "filter": lambda: self.set_filter_enabled(
                not self._settings.filter_enabled
            ),
            "break": lambda: self.set_break_enabled(
                not self._settings.break_enabled
            ),
            "dimmer": lambda: self.set_dimmer_enabled(
                not self._settings.dimmer_enabled
            ),
            "focus": lambda: self.set_focus_enabled(
                not self._settings.focus_enabled
            ),
        }

    def _build_state(self) -> AppState:
        reminder = self._break_reminder
        scheduler = self._scheduler
        until = self._settings.global_pause_until
        until_datetime = (
            datetime.fromtimestamp(until).astimezone() if until is not None else None
        )
        return AppState(
            display=DisplayState(
                filter_enabled=self._settings.filter_enabled,
                color_temperature=self._settings.color_temperature,
                dimmer_enabled=self._settings.dimmer_enabled,
                dim_level=self._settings.dim_level,
                preset=self._settings.current_preset,
            ),
            breaks=BreakState(
                enabled=self._settings.break_enabled,
                phase=getattr(reminder, "phase", "stopped"),
                mode=self._settings.break_mode,
                work_duration=self._settings.work_duration,
                break_duration=self._settings.break_duration,
                remaining=getattr(reminder, "remaining", 0),
                total=getattr(reminder, "total", 0),
                paused=getattr(reminder, "paused", False),
                force_break=self._settings.force_break,
                countdown_display=self._settings.break_countdown_display,
            ),
            focus=FocusState(
                enabled=self._settings.focus_enabled,
                dim_level=self._settings.focus_dim_level,
                session_ends_at=self._focus_session_ends_at,
            ),
            automation=AutomationState(
                enabled=self._settings.filter_schedule_enabled,
                mode=self._settings.schedule_mode,
                next_event=getattr(scheduler, "next_event", None),
                next_event_at=getattr(scheduler, "next_event_at", None),
                manual_override=getattr(scheduler, "manual_override", False),
                on_time=self._settings.schedule_on_time,
                off_time=self._settings.schedule_off_time,
                days=self._settings.schedule_days,
            ),
            global_pause=GlobalPauseState(
                active=self._is_globally_paused(),
                mode=(
                    self._settings.global_pause_mode
                    if self._is_globally_paused()
                    else "none"
                ),
                until=until_datetime if self._is_globally_paused() else None,
            ),
            capabilities=CapabilitiesState(
                filter_available=self._blue_filter is not None,
                dimmer_available=self._dimmer is not None,
                breaks_available=self._break_reminder is not None,
                focus_available=self._focus_mode is not None,
                automation_available=self._scheduler is not None,
                hotkeys_available=(
                    self._hotkeys is not None
                    and bool(getattr(self._hotkeys, "available", False))
                ),
            ),
            general=GeneralState(
                theme=self._settings.theme,
                autostart=self._settings.autostart,
                onboarding_completed=self._settings.onboarding_completed,
                location_configured=self._settings.location_configured,
                city=self._settings.city,
                latitude=(
                    self._settings.latitude
                    if self._settings.location_configured
                    else None
                ),
                longitude=(
                    self._settings.longitude
                    if self._settings.location_configured
                    else None
                ),
                hotkeys=HotkeyState(
                    filter=self._settings.hotkey_filter,
                    breaks=self._settings.hotkey_break,
                    dimmer=self._settings.hotkey_dimmer,
                    focus=self._settings.hotkey_focus,
                ),
            ),
        )

    @staticmethod
    def _valid_clock_time(value: str) -> bool:
        try:
            datetime.strptime(value, "%H:%M")
            return True
        except (TypeError, ValueError):
            return False
