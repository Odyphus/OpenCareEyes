"""QSettings-based configuration management.

Schema v2 deliberately keeps the v0.1.1 keys in place.  This makes the
migration lossless (and lets older portable builds read the basic settings)
while adding an explicit schema marker and the v0.2-only values.
"""

from __future__ import annotations

import os
from collections.abc import Iterable

from PySide6.QtCore import QSettings

from opencareyes.constants import (
    APP_NAME,
    BREAK_DURATION_DEFAULT,
    DIM_DEFAULT,
    FOCUS_DIM_DEFAULT,
    HOTKEY_TOGGLE_BREAK,
    HOTKEY_TOGGLE_DIMMER,
    HOTKEY_TOGGLE_FILTER,
    HOTKEY_TOGGLE_FOCUS,
    MICRO_BREAK_DURATION_DEFAULT,
    MICRO_BREAK_INTERVAL_DEFAULT,
    ORG_NAME,
    TEMP_DEFAULT,
    WORK_DURATION_DEFAULT,
)


SCHEMA_VERSION = 2


class Settings:
    """Thin wrapper around :class:`QSettings` with typed accessors.

    ``store`` is injectable for tests and for portable-build backends.  The
    no-argument constructor remains fully compatible with v0.1.1.
    """

    def __init__(self, store: QSettings | None = None):
        if store is not None:
            self._s = store
        else:
            settings_path = os.environ.get("OPENCAREYES_SETTINGS_PATH")
            self._s = (
                QSettings(settings_path, QSettings.IniFormat)
                if settings_path
                else QSettings(ORG_NAME, APP_NAME)
            )
        self._migrate_to_v2()

    def _migrate_to_v2(self) -> None:
        raw_version = self._s.value("meta/schema_version", 1)
        try:
            version = int(raw_version)
        except (TypeError, ValueError):
            version = 1
        if version >= SCHEMA_VERSION:
            return

        # Existing explicit coordinates came from a user's v0.1.1 config.  A
        # fresh v0.2 install keeps location unconfigured instead of silently
        # treating the old Beijing defaults as consent.
        latitude = self._s.value("location/latitude", None)
        longitude = self._s.value("location/longitude", None)
        if latitude is not None and longitude is not None:
            self._s.setValue("location/configured", True)

        try:
            old_keys = set(self._s.allKeys() or ())
        except (AttributeError, TypeError):
            old_keys = set()
        if old_keys - {"meta/schema_version"} and self._s.value(
            "general/onboarding_completed", None
        ) is None:
            self._s.setValue("general/onboarding_completed", True)
            self._s.setValue("general/first_run_complete", True)

        self._s.setValue("meta/schema_version", SCHEMA_VERSION)

    @property
    def schema_version(self) -> int:
        return SCHEMA_VERSION

    # ---- Blue light filter ----
    @property
    def filter_enabled(self) -> bool:
        return self._s.value("filter/enabled", False, type=bool)

    @filter_enabled.setter
    def filter_enabled(self, value: bool) -> None:
        self._s.setValue("filter/enabled", bool(value))

    @property
    def color_temperature(self) -> int:
        return self._s.value("filter/temperature", TEMP_DEFAULT, type=int)

    @color_temperature.setter
    def color_temperature(self, value: int) -> None:
        self._s.setValue("filter/temperature", int(value))

    @property
    def filter_schedule_enabled(self) -> bool:
        return self._s.value("filter/schedule_enabled", False, type=bool)

    @filter_schedule_enabled.setter
    def filter_schedule_enabled(self, value: bool) -> None:
        self._s.setValue("filter/schedule_enabled", bool(value))

    # Semantic alias used by the controller.
    schedule_enabled = filter_schedule_enabled

    @property
    def schedule_mode(self) -> str:
        return self._s.value("automation/mode", "sun", type=str)

    @schedule_mode.setter
    def schedule_mode(self, value: str) -> None:
        self._s.setValue("automation/mode", value)

    @property
    def schedule_on_time(self) -> str:
        return self._s.value("automation/on_time", "19:00", type=str)

    @schedule_on_time.setter
    def schedule_on_time(self, value: str) -> None:
        self._s.setValue("automation/on_time", value)

    @property
    def schedule_off_time(self) -> str:
        return self._s.value("automation/off_time", "07:00", type=str)

    @schedule_off_time.setter
    def schedule_off_time(self, value: str) -> None:
        self._s.setValue("automation/off_time", value)

    @property
    def schedule_days(self) -> tuple[int, ...]:
        value = self._s.value("automation/days", [0, 1, 2, 3, 4, 5, 6])
        if isinstance(value, str):
            value = value.split(",")
        try:
            return tuple(sorted({int(day) for day in value if 0 <= int(day) <= 6}))
        except (TypeError, ValueError):
            return (0, 1, 2, 3, 4, 5, 6)

    @schedule_days.setter
    def schedule_days(self, value: Iterable[int]) -> None:
        days = sorted({int(day) for day in value if 0 <= int(day) <= 6})
        self._s.setValue("automation/days", days)

    # ---- Screen dimmer ----
    @property
    def dimmer_enabled(self) -> bool:
        return self._s.value("dimmer/enabled", False, type=bool)

    @dimmer_enabled.setter
    def dimmer_enabled(self, value: bool) -> None:
        self._s.setValue("dimmer/enabled", bool(value))

    @property
    def dim_level(self) -> int:
        return self._s.value("dimmer/level", DIM_DEFAULT, type=int)

    @dim_level.setter
    def dim_level(self, value: int) -> None:
        self._s.setValue("dimmer/level", int(value))

    # ---- Break reminder ----
    @property
    def break_enabled(self) -> bool:
        return self._s.value("break/enabled", False, type=bool)

    @break_enabled.setter
    def break_enabled(self, value: bool) -> None:
        self._s.setValue("break/enabled", bool(value))

    @property
    def work_duration(self) -> int:
        return self._s.value("break/work_duration", WORK_DURATION_DEFAULT, type=int)

    @work_duration.setter
    def work_duration(self, value: int) -> None:
        self._s.setValue("break/work_duration", int(value))

    @property
    def break_duration(self) -> int:
        return self._s.value("break/break_duration", BREAK_DURATION_DEFAULT, type=int)

    @break_duration.setter
    def break_duration(self, value: int) -> None:
        self._s.setValue("break/break_duration", int(value))

    @property
    def break_mode(self) -> str:
        return self._s.value("break/mode", "pomodoro", type=str)

    @break_mode.setter
    def break_mode(self, value: str) -> None:
        self._s.setValue("break/mode", value)

    @property
    def micro_break_interval(self) -> int:
        return self._s.value(
            "break/micro_interval", MICRO_BREAK_INTERVAL_DEFAULT, type=int
        )

    @micro_break_interval.setter
    def micro_break_interval(self, value: int) -> None:
        self._s.setValue("break/micro_interval", int(value))

    @property
    def micro_break_duration(self) -> int:
        return self._s.value(
            "break/micro_duration", MICRO_BREAK_DURATION_DEFAULT, type=int
        )

    @micro_break_duration.setter
    def micro_break_duration(self, value: int) -> None:
        self._s.setValue("break/micro_duration", int(value))

    @property
    def force_break(self) -> bool:
        return self._s.value("break/force", False, type=bool)

    @force_break.setter
    def force_break(self, value: bool) -> None:
        self._s.setValue("break/force", bool(value))

    @property
    def break_countdown_display(self) -> str:
        value = self._s.value("break/countdown_display", "tray", type=str)
        return value if value in {"floating", "tray", "hidden"} else "tray"

    @break_countdown_display.setter
    def break_countdown_display(self, value: str) -> None:
        if value not in {"floating", "tray", "hidden"}:
            raise ValueError(f"Unknown countdown display mode: {value}")
        self._s.setValue("break/countdown_display", value)

    # ---- Focus mode ----
    @property
    def focus_enabled(self) -> bool:
        return self._s.value("focus/enabled", False, type=bool)

    @focus_enabled.setter
    def focus_enabled(self, value: bool) -> None:
        self._s.setValue("focus/enabled", bool(value))

    @property
    def focus_dim_level(self) -> int:
        return self._s.value("focus/dim_level", FOCUS_DIM_DEFAULT, type=int)

    @focus_dim_level.setter
    def focus_dim_level(self, value: int) -> None:
        self._s.setValue("focus/dim_level", int(value))

    # ---- General ----
    @property
    def autostart(self) -> bool:
        return self._s.value("general/autostart", False, type=bool)

    @autostart.setter
    def autostart(self, value: bool) -> None:
        self._s.setValue("general/autostart", bool(value))

    @property
    def theme(self) -> str:
        return self._s.value("general/theme", "system", type=str)

    @theme.setter
    def theme(self, value: str) -> None:
        self._s.setValue("general/theme", value)

    @property
    def first_run_complete(self) -> bool:
        return self.onboarding_completed

    @first_run_complete.setter
    def first_run_complete(self, value: bool) -> None:
        self.onboarding_completed = value

    @property
    def onboarding_completed(self) -> bool:
        legacy = self._s.value("general/first_run_complete", False, type=bool)
        return self._s.value(
            "general/onboarding_completed", legacy, type=bool
        )

    @onboarding_completed.setter
    def onboarding_completed(self, value: bool) -> None:
        completed = bool(value)
        self._s.setValue("general/onboarding_completed", completed)
        self._s.setValue("general/first_run_complete", completed)

    @property
    def latitude(self) -> float:
        # Compatibility fallback only.  ``location_configured`` determines
        # whether automation may use it.
        return self._s.value("location/latitude", 39.9, type=float)

    @latitude.setter
    def latitude(self, value: float) -> None:
        self._s.setValue("location/latitude", float(value))

    @property
    def longitude(self) -> float:
        return self._s.value("location/longitude", 116.4, type=float)

    @longitude.setter
    def longitude(self, value: float) -> None:
        self._s.setValue("location/longitude", float(value))

    @property
    def location_configured(self) -> bool:
        return self._s.value("location/configured", False, type=bool)

    @location_configured.setter
    def location_configured(self, value: bool) -> None:
        self._s.setValue("location/configured", bool(value))

    @property
    def city(self) -> str:
        return self._s.value("location/city", "", type=str)

    @city.setter
    def city(self, value: str) -> None:
        self._s.setValue("location/city", value)

    # ---- Hotkeys ----
    @property
    def hotkey_filter(self) -> str:
        return self._s.value("hotkeys/filter", HOTKEY_TOGGLE_FILTER, type=str)

    @hotkey_filter.setter
    def hotkey_filter(self, value: str) -> None:
        self._s.setValue("hotkeys/filter", value)

    @property
    def hotkey_break(self) -> str:
        return self._s.value("hotkeys/break", HOTKEY_TOGGLE_BREAK, type=str)

    @hotkey_break.setter
    def hotkey_break(self, value: str) -> None:
        self._s.setValue("hotkeys/break", value)

    @property
    def hotkey_dimmer(self) -> str:
        return self._s.value("hotkeys/dimmer", HOTKEY_TOGGLE_DIMMER, type=str)

    @hotkey_dimmer.setter
    def hotkey_dimmer(self, value: str) -> None:
        self._s.setValue("hotkeys/dimmer", value)

    @property
    def hotkey_focus(self) -> str:
        return self._s.value("hotkeys/focus", HOTKEY_TOGGLE_FOCUS, type=str)

    @hotkey_focus.setter
    def hotkey_focus(self, value: str) -> None:
        self._s.setValue("hotkeys/focus", value)

    # ---- Preset ----
    @property
    def current_preset(self) -> str:
        return self._s.value("preset/current", "custom", type=str)

    @current_preset.setter
    def current_preset(self, value: str) -> None:
        self._s.setValue("preset/current", value)

    # ---- Temporary global pause ----
    @property
    def global_pause_mode(self) -> str:
        return self._s.value("pause/mode", "none", type=str)

    @global_pause_mode.setter
    def global_pause_mode(self, value: str) -> None:
        self._s.setValue("pause/mode", value)

    @property
    def global_pause_until(self) -> float | None:
        value = self._s.value("pause/until", None)
        if value in (None, ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @global_pause_until.setter
    def global_pause_until(self, value: float | None) -> None:
        self._s.setValue("pause/until", "" if value is None else float(value))

    def sync(self) -> None:
        self._s.sync()

    def reset(self) -> None:
        """Clear user settings and recreate a fresh schema-v2 marker."""
        self._s.clear()
        self._s.setValue("meta/schema_version", SCHEMA_VERSION)
        self._s.sync()
