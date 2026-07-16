"""QSettings-based configuration management and schema migrations."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from enum import Enum
from typing import Any, TypedDict

from PySide6.QtCore import QSettings

from opencareyes.config.defaults import DEFAULT_PREFERENCES, LEGACY_V2_PREFERENCES
from opencareyes.config.presets import PRESETS
from opencareyes.constants import APP_NAME, ORG_NAME


SCHEMA_VERSION = 6

_PET_ID_PATTERN = re.compile(r'^[a-z0-9_]{1,64}$')
_ITEM_ID_PATTERN = re.compile(r'^[a-z0-9_.-]{1,64}$')
_CLOCK_PATTERN = re.compile(r'^(?:[01]\d|2[0-3]):[0-5]\d$')
_PET_ANCHOR_EDGES = {'bottom_right', 'bottom_left', 'top_right', 'top_left', 'free'}
_PET_ACCESSORY_SLOTS = {
    'headwear',
    'neckwear',
    'bodywear',
    'held_item',
    'scene',
    'effect',
}
_REST_SCENES = {'gaze', 'snow_breathing', 'stretch', 'sleep'}
_QUICK_ACTIONS = {'rest', 'timer', 'notes', 'system', 'wardrobe', 'more'}


class SettingsReadOnlyError(RuntimeError):
    """Raised when this build cannot safely write a newer settings schema."""


class SettingsMigrationError(RuntimeError):
    """Raised after a failed migration has been rolled back."""


class SettingsTransactionError(RuntimeError):
    """Raised when a preference transaction cannot be rolled back cleanly."""


class AppRule(TypedDict):
    app_id: str
    breaks: bool
    focus: bool
    filter: bool
    dimmer: bool


class AppPropRule(TypedDict):
    app_id: str
    prop_id: str


_APP_RULE_FLAGS = ("breaks", "focus", "filter", "dimmer")


def _validated_app_rule(rule: Mapping[str, object]) -> AppRule:
    raw_app_id = rule.get("app_id")
    if not isinstance(raw_app_id, str):
        raise ValueError("app_id must be an executable filename")
    app_id = raw_app_id.strip().lower()
    if (
        not app_id
        or len(app_id) > 128
        or not app_id.endswith(".exe")
        or any(separator in app_id for separator in ("/", "\\", ":"))
    ):
        raise ValueError("app_id must be a basename ending in .exe")
    for flag in _APP_RULE_FLAGS:
        if type(rule.get(flag)) is not bool:
            raise ValueError(f"{flag} must be a bool")
    return AppRule(
        app_id=app_id,
        breaks=bool(rule["breaks"]),
        focus=bool(rule["focus"]),
        filter=bool(rule["filter"]),
        dimmer=bool(rule["dimmer"]),
    )


def _schema_version(raw_version: object) -> int:
    try:
        return max(1, int(raw_version))
    except (TypeError, ValueError):
        return 1


def _snapshot_store(store: Any) -> dict[str, object]:
    try:
        keys = tuple(store.allKeys() or ())
    except (AttributeError, TypeError):
        keys = ()
    return {str(key): store.value(key, None) for key in keys}


def _sync_store_checked(store: Any) -> None:
    sync = getattr(store, "sync", None)
    if callable(sync):
        sync()
    status_method = getattr(store, "status", None)
    if not callable(status_method):
        return
    status = status_method()
    if (type(status) is int and status != 0) or (
        isinstance(status, Enum) and status.name != "NoError"
    ):
        raise OSError(f"Settings backend sync failed: {status}")


def _restore_store(store: Any, snapshot: Mapping[str, object]) -> None:
    store.clear()
    for key, value in snapshot.items():
        store.setValue(key, value)


def _validated_profile(value: object) -> str:
    profile = str(value).strip().lower()
    if profile not in PRESETS:
        raise ValueError(f"Unknown display profile: {value}")
    return profile


def _validated_offset(value: object) -> int:
    offset = int(value)
    if not -120 <= offset <= 120:
        raise ValueError("Sunrise and sunset offsets must be between -120 and 120")
    return offset


def _validated_pet_id(value: object) -> str:
    pet_id = str(value).strip().lower()
    if not _PET_ID_PATTERN.fullmatch(pet_id):
        raise ValueError('pet_id must contain only lowercase letters, digits, or underscores')
    return pet_id


def _validated_item_id(value: object) -> str:
    item_id = str(value).strip().lower()
    if not _ITEM_ID_PATTERN.fullmatch(item_id):
        raise ValueError('item id must contain only safe identifier characters')
    return item_id


def _validated_app_id(value: object) -> str:
    app_id = str(value).strip().lower()
    if (
        not app_id
        or len(app_id) > 128
        or not app_id.endswith('.exe')
        or any(separator in app_id for separator in ('/', '\\', ':'))
    ):
        raise ValueError('app_id must be a basename ending in .exe')
    return app_id


def _validated_app_prop_rule(rule: Mapping[str, object]) -> AppPropRule:
    return AppPropRule(
        app_id=_validated_app_id(rule.get('app_id', '')),
        prop_id=_validated_item_id(rule.get('prop_id', '')),
    )


class SettingsMigrator:
    """Apply ordered settings migrations with snapshot-based rollback."""

    def __init__(self, store: Any):
        self._store = store

    def migrate(self) -> tuple[int, bool]:
        version = _schema_version(self._store.value("meta/schema_version", 1))
        if version > SCHEMA_VERSION:
            return version, True
        if version == SCHEMA_VERSION:
            return version, False

        snapshot = self._snapshot()
        existing_profile = (
            "meta/schema_version" in snapshot
            or bool(set(snapshot) - {"meta/schema_version"})
        )
        try:
            if version < 2:
                self._migrate_v1_to_v2(existing_profile)
                version = 2
            if version < 3:
                self._migrate_v2_to_v3(existing_profile)
                version = 3
            if version < 4:
                self._migrate_v3_to_v4(existing_profile)
                version = 4
            if version < 5:
                self._migrate_v4_to_v5(existing_profile)
                version = 5
            if version < 6:
                self._migrate_v5_to_v6(existing_profile)
                version = 6
            self._sync_checked()
        except Exception as exc:
            self._restore(snapshot)
            raise SettingsMigrationError(
                f"Unable to migrate settings to schema v{SCHEMA_VERSION}; "
                "the previous settings were restored"
            ) from exc
        return version, False

    def _snapshot(self) -> dict[str, object]:
        return _snapshot_store(self._store)

    def _migrate_v1_to_v2(self, existing_profile: bool) -> None:
        latitude = self._store.value("location/latitude", None)
        longitude = self._store.value("location/longitude", None)
        if latitude is not None and longitude is not None:
            self._store.setValue("location/configured", True)

        if existing_profile and self._store.value(
            "general/onboarding_completed", None
        ) is None:
            self._store.setValue("general/onboarding_completed", True)
            self._store.setValue("general/first_run_complete", True)
        self._store.setValue("meta/schema_version", 2)

    def _migrate_v2_to_v3(self, existing_profile: bool) -> None:
        if existing_profile:
            legacy_values = {
                "break/mode": LEGACY_V2_PREFERENCES.break_mode,
                "break/work_duration": LEGACY_V2_PREFERENCES.work_duration,
                "break/break_duration": LEGACY_V2_PREFERENCES.break_duration,
                "automation/mode": LEGACY_V2_PREFERENCES.schedule_mode,
                "automation/on_time": LEGACY_V2_PREFERENCES.schedule_on_time,
                "automation/off_time": LEGACY_V2_PREFERENCES.schedule_off_time,
                "automation/days": list(LEGACY_V2_PREFERENCES.schedule_days),
            }
            for key, value in legacy_values.items():
                if self._store.value(key, None) is None:
                    self._store.setValue(key, value)
        self._store.setValue("meta/schema_version", 3)

    def _migrate_v3_to_v4(self, existing_profile: bool) -> None:
        if existing_profile:
            legacy_values = {
                "break/reminder_style": "fullscreen",
                "break/cadence_mode": self._store.value(
                    "break/mode", DEFAULT_PREFERENCES.break_mode
                ),
                "break/cadence_short_interval": self._store.value(
                    "break/work_duration", DEFAULT_PREFERENCES.work_duration
                ),
                "break/cadence_short_duration": self._store.value(
                    "break/break_duration", DEFAULT_PREFERENCES.break_duration
                ),
                "break/cadence_long_enabled": False,
                "break/cadence_long_interval": (
                    DEFAULT_PREFERENCES.cadence_long_interval
                ),
                "break/cadence_long_duration": (
                    DEFAULT_PREFERENCES.cadence_long_duration
                ),
                "automation/day_profile": (
                    DEFAULT_PREFERENCES.schedule_day_profile
                ),
                "automation/night_profile": (
                    DEFAULT_PREFERENCES.schedule_night_profile
                ),
                "automation/sunrise_offset": DEFAULT_PREFERENCES.sunrise_offset,
                "automation/sunset_offset": DEFAULT_PREFERENCES.sunset_offset,
            }
            for key, value in legacy_values.items():
                if self._store.value(key, None) is None:
                    self._store.setValue(key, value)

            mode = self._store.value(
                "automation/mode", DEFAULT_PREFERENCES.schedule_mode
            )
            if mode in {"sun", "sunrise_sunset", "astral"}:
                # v3 did not apply weekday filtering in sun mode.  Materialise
                # all days so an upgrade keeps the same effective schedule.
                self._store.setValue("automation/days", list(range(7)))
        self._store.setValue("meta/schema_version", 4)

    def _migrate_v4_to_v5(self, existing_profile: bool) -> None:
        if existing_profile:
            countdown_display = str(
                self._store.value(
                    'break/countdown_display',
                    DEFAULT_PREFERENCES.break_countdown_display,
                )
            )
            legacy_x = self._store.value('ui/pet_x', None)
            legacy_y = self._store.value('ui/pet_y', None)
            has_legacy_position = False
            try:
                int(legacy_x)
                int(legacy_y)
                has_legacy_position = legacy_x not in {None, ''} and legacy_y not in {None, ''}
            except (TypeError, ValueError):
                pass
            legacy_values = {
                'companion/enabled': countdown_display == 'floating',
                'companion/active_pet_id': DEFAULT_PREFERENCES.active_pet_id,
                'companion/recovery_pet_id': DEFAULT_PREFERENCES.recovery_pet_id,
                'companion/scale_percent': DEFAULT_PREFERENCES.pet_scale_percent,
                'companion/anchor_edge': (
                    'free' if has_legacy_position else DEFAULT_PREFERENCES.pet_anchor_edge
                ),
                'companion/anchor_offset': (
                    0 if has_legacy_position else DEFAULT_PREFERENCES.pet_anchor_offset
                ),
                'companion/follow_active_monitor': (
                    DEFAULT_PREFERENCES.follow_active_monitor
                ),
                'companion/window_avoidance_enabled': (
                    DEFAULT_PREFERENCES.window_avoidance_enabled
                ),
                'companion/sound_enabled': (
                    DEFAULT_PREFERENCES.companion_sound_enabled
                ),
                'companion/hourly_chime_enabled': (
                    DEFAULT_PREFERENCES.hourly_chime_enabled
                ),
                'companion/quiet_hours_start': (
                    DEFAULT_PREFERENCES.quiet_hours_start
                ),
                'companion/quiet_hours_end': DEFAULT_PREFERENCES.quiet_hours_end,
                'companion/pet_preferences_json': '{}',
                'companion/app_prop_rules_json': '[]',
                'weather/enabled': False,
                'holiday/pack': DEFAULT_PREFERENCES.holiday_pack,
                'break/rest_scene': DEFAULT_PREFERENCES.rest_scene,
            }
            for key, value in legacy_values.items():
                if self._store.value(key, None) is None:
                    self._store.setValue(key, value)
        self._store.setValue('meta/schema_version', 5)

    def _migrate_v5_to_v6(self, existing_profile: bool) -> None:
        if existing_profile and self._store.value(
            'companion/quick_actions_json', None
        ) is None:
            self._store.setValue(
                'companion/quick_actions_json',
                json.dumps(
                    DEFAULT_PREFERENCES.quick_actions,
                    ensure_ascii=True,
                    separators=(',', ':'),
                ),
            )
        self._store.setValue('meta/schema_version', 6)

    def _sync_checked(self) -> None:
        _sync_store_checked(self._store)

    def _restore(self, snapshot: Mapping[str, object]) -> None:
        _restore_store(self._store, snapshot)
        sync = getattr(self._store, "sync", None)
        if callable(sync):
            try:
                sync()
            except Exception:
                # The original backend error remains the useful failure.  A
                # failed sync cannot overwrite the pre-migration persisted
                # data, while the in-process store has still been restored.
                pass


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
        self._stored_schema_version, self._read_only = SettingsMigrator(
            self._s
        ).migrate()

    @property
    def schema_version(self) -> int:
        """The schema version currently stored by the backend."""
        return self._stored_schema_version

    @property
    def stored_schema_version(self) -> int:
        return self._stored_schema_version

    @property
    def read_only(self) -> bool:
        return self._read_only

    def _set_value(self, key: str, value: object) -> None:
        if self._read_only:
            raise SettingsReadOnlyError(
                f"Settings schema v{self._stored_schema_version} is newer than "
                f"the supported schema v{SCHEMA_VERSION}; settings are read-only"
            )
        self._s.setValue(key, value)

    # ---- Blue light filter ----
    @property
    def filter_enabled(self) -> bool:
        return self._s.value(
            "filter/enabled", DEFAULT_PREFERENCES.filter_enabled, type=bool
        )

    @filter_enabled.setter
    def filter_enabled(self, value: bool) -> None:
        self._set_value("filter/enabled", bool(value))

    @property
    def color_temperature(self) -> int:
        return self._s.value(
            "filter/temperature", DEFAULT_PREFERENCES.color_temperature, type=int
        )

    @color_temperature.setter
    def color_temperature(self, value: int) -> None:
        self._set_value("filter/temperature", int(value))

    @property
    def filter_schedule_enabled(self) -> bool:
        return self._s.value(
            "filter/schedule_enabled",
            DEFAULT_PREFERENCES.schedule_enabled,
            type=bool,
        )

    @filter_schedule_enabled.setter
    def filter_schedule_enabled(self, value: bool) -> None:
        self._set_value("filter/schedule_enabled", bool(value))

    # Semantic alias used by the controller.
    schedule_enabled = filter_schedule_enabled

    @property
    def schedule_mode(self) -> str:
        return self._s.value(
            "automation/mode", DEFAULT_PREFERENCES.schedule_mode, type=str
        )

    @schedule_mode.setter
    def schedule_mode(self, value: str) -> None:
        self._set_value("automation/mode", value)

    @property
    def schedule_on_time(self) -> str:
        return self._s.value(
            "automation/on_time", DEFAULT_PREFERENCES.schedule_on_time, type=str
        )

    @schedule_on_time.setter
    def schedule_on_time(self, value: str) -> None:
        self._set_value("automation/on_time", value)

    @property
    def schedule_off_time(self) -> str:
        return self._s.value(
            "automation/off_time", DEFAULT_PREFERENCES.schedule_off_time, type=str
        )

    @schedule_off_time.setter
    def schedule_off_time(self, value: str) -> None:
        self._set_value("automation/off_time", value)

    @property
    def schedule_days(self) -> tuple[int, ...]:
        value = self._s.value(
            "automation/days", list(DEFAULT_PREFERENCES.schedule_days)
        )
        if isinstance(value, str):
            value = value.split(",")
        try:
            return tuple(sorted({int(day) for day in value if 0 <= int(day) <= 6}))
        except (TypeError, ValueError):
            return DEFAULT_PREFERENCES.schedule_days

    @schedule_days.setter
    def schedule_days(self, value: Iterable[int]) -> None:
        days = sorted({int(day) for day in value if 0 <= int(day) <= 6})
        self._set_value("automation/days", days)

    @property
    def schedule_day_profile(self) -> str:
        value = self._s.value(
            "automation/day_profile",
            DEFAULT_PREFERENCES.schedule_day_profile,
            type=str,
        )
        try:
            return _validated_profile(value)
        except ValueError:
            return DEFAULT_PREFERENCES.schedule_day_profile

    @schedule_day_profile.setter
    def schedule_day_profile(self, value: str) -> None:
        self._set_value("automation/day_profile", _validated_profile(value))

    @property
    def schedule_night_profile(self) -> str:
        value = self._s.value(
            "automation/night_profile",
            DEFAULT_PREFERENCES.schedule_night_profile,
            type=str,
        )
        try:
            return _validated_profile(value)
        except ValueError:
            return DEFAULT_PREFERENCES.schedule_night_profile

    @schedule_night_profile.setter
    def schedule_night_profile(self, value: str) -> None:
        self._set_value("automation/night_profile", _validated_profile(value))

    @property
    def sunrise_offset(self) -> int:
        value = self._s.value(
            "automation/sunrise_offset",
            DEFAULT_PREFERENCES.sunrise_offset,
            type=int,
        )
        try:
            return _validated_offset(value)
        except (TypeError, ValueError):
            return DEFAULT_PREFERENCES.sunrise_offset

    @sunrise_offset.setter
    def sunrise_offset(self, value: int) -> None:
        self._set_value("automation/sunrise_offset", _validated_offset(value))

    @property
    def sunset_offset(self) -> int:
        value = self._s.value(
            "automation/sunset_offset",
            DEFAULT_PREFERENCES.sunset_offset,
            type=int,
        )
        try:
            return _validated_offset(value)
        except (TypeError, ValueError):
            return DEFAULT_PREFERENCES.sunset_offset

    @sunset_offset.setter
    def sunset_offset(self, value: int) -> None:
        self._set_value("automation/sunset_offset", _validated_offset(value))

    # ---- Screen dimmer ----
    @property
    def dimmer_enabled(self) -> bool:
        return self._s.value(
            "dimmer/enabled", DEFAULT_PREFERENCES.dimmer_enabled, type=bool
        )

    @dimmer_enabled.setter
    def dimmer_enabled(self, value: bool) -> None:
        self._set_value("dimmer/enabled", bool(value))

    @property
    def dim_level(self) -> int:
        return self._s.value(
            "dimmer/level", DEFAULT_PREFERENCES.dim_level, type=int
        )

    @dim_level.setter
    def dim_level(self, value: int) -> None:
        self._set_value("dimmer/level", int(value))

    # ---- Break reminder ----
    @property
    def break_enabled(self) -> bool:
        return self._s.value(
            "break/enabled", DEFAULT_PREFERENCES.break_enabled, type=bool
        )

    @break_enabled.setter
    def break_enabled(self, value: bool) -> None:
        self._set_value("break/enabled", bool(value))

    @property
    def work_duration(self) -> int:
        legacy = self._s.value(
            "break/work_duration", DEFAULT_PREFERENCES.work_duration, type=int
        )
        return self._s.value(
            "break/cadence_short_interval", legacy, type=int
        )

    @work_duration.setter
    def work_duration(self, value: int) -> None:
        duration = int(value)
        self._set_value("break/work_duration", duration)
        self._set_value("break/cadence_short_interval", duration)

    @property
    def break_duration(self) -> int:
        legacy = self._s.value(
            "break/break_duration", DEFAULT_PREFERENCES.break_duration, type=int
        )
        return self._s.value(
            "break/cadence_short_duration", legacy, type=int
        )

    @break_duration.setter
    def break_duration(self, value: int) -> None:
        duration = int(value)
        self._set_value("break/break_duration", duration)
        self._set_value("break/cadence_short_duration", duration)

    @property
    def break_mode(self) -> str:
        legacy = self._s.value(
            "break/mode", DEFAULT_PREFERENCES.break_mode, type=str
        )
        return self._s.value(
            "break/cadence_mode", legacy, type=str
        )

    @break_mode.setter
    def break_mode(self, value: str) -> None:
        mode = str(value)
        self._set_value("break/mode", mode)
        self._set_value("break/cadence_mode", mode)

    @property
    def break_reminder_style(self) -> str:
        value = self._s.value(
            "break/reminder_style",
            DEFAULT_PREFERENCES.break_reminder_style,
            type=str,
        )
        return value if value in {"progressive", "fullscreen"} else "progressive"

    @break_reminder_style.setter
    def break_reminder_style(self, value: str) -> None:
        if value not in {"progressive", "fullscreen"}:
            raise ValueError(f"Unknown break reminder style: {value}")
        self._set_value("break/reminder_style", value)

    @property
    def cadence_mode(self) -> str:
        return self.break_mode

    @cadence_mode.setter
    def cadence_mode(self, value: str) -> None:
        self.break_mode = value

    @property
    def cadence_short_interval(self) -> int:
        return self.work_duration

    @cadence_short_interval.setter
    def cadence_short_interval(self, value: int) -> None:
        if int(value) <= 0:
            raise ValueError("Short break interval must be positive")
        self.work_duration = value

    @property
    def cadence_short_duration(self) -> int:
        return self.break_duration

    @cadence_short_duration.setter
    def cadence_short_duration(self, value: int) -> None:
        if int(value) <= 0:
            raise ValueError("Short break duration must be positive")
        self.break_duration = value

    @property
    def cadence_long_enabled(self) -> bool:
        return self._s.value(
            "break/cadence_long_enabled",
            DEFAULT_PREFERENCES.cadence_long_enabled,
            type=bool,
        )

    @cadence_long_enabled.setter
    def cadence_long_enabled(self, value: bool) -> None:
        self._set_value("break/cadence_long_enabled", bool(value))

    @property
    def cadence_long_interval(self) -> int:
        return self._s.value(
            "break/cadence_long_interval",
            DEFAULT_PREFERENCES.cadence_long_interval,
            type=int,
        )

    @cadence_long_interval.setter
    def cadence_long_interval(self, value: int) -> None:
        if int(value) <= 0:
            raise ValueError("Long break interval must be positive")
        self._set_value("break/cadence_long_interval", int(value))

    @property
    def cadence_long_duration(self) -> int:
        return self._s.value(
            "break/cadence_long_duration",
            DEFAULT_PREFERENCES.cadence_long_duration,
            type=int,
        )

    @cadence_long_duration.setter
    def cadence_long_duration(self, value: int) -> None:
        if int(value) <= 0:
            raise ValueError("Long break duration must be positive")
        self._set_value("break/cadence_long_duration", int(value))

    @property
    def micro_break_interval(self) -> int:
        return self._s.value(
            "break/micro_interval",
            DEFAULT_PREFERENCES.micro_break_interval,
            type=int,
        )

    @micro_break_interval.setter
    def micro_break_interval(self, value: int) -> None:
        self._set_value("break/micro_interval", int(value))

    @property
    def micro_break_duration(self) -> int:
        return self._s.value(
            "break/micro_duration",
            DEFAULT_PREFERENCES.micro_break_duration,
            type=int,
        )

    @micro_break_duration.setter
    def micro_break_duration(self, value: int) -> None:
        self._set_value("break/micro_duration", int(value))

    @property
    def force_break(self) -> bool:
        return self._s.value(
            "break/force", DEFAULT_PREFERENCES.force_break, type=bool
        )

    @force_break.setter
    def force_break(self, value: bool) -> None:
        self._set_value("break/force", bool(value))

    @property
    def break_countdown_display(self) -> str:
        value = self._s.value(
            "break/countdown_display",
            DEFAULT_PREFERENCES.break_countdown_display,
            type=str,
        )
        return value if value in {"floating", "tray", "hidden"} else "tray"

    @break_countdown_display.setter
    def break_countdown_display(self, value: str) -> None:
        if value not in {"floating", "tray", "hidden"}:
            raise ValueError(f"Unknown countdown display mode: {value}")
        self._set_value("break/countdown_display", value)

    # ---- Focus mode ----
    @property
    def focus_enabled(self) -> bool:
        return self._s.value(
            "focus/enabled", DEFAULT_PREFERENCES.focus_enabled, type=bool
        )

    @focus_enabled.setter
    def focus_enabled(self, value: bool) -> None:
        self._set_value("focus/enabled", bool(value))

    @property
    def focus_dim_level(self) -> int:
        return self._s.value(
            "focus/dim_level", DEFAULT_PREFERENCES.focus_dim_level, type=int
        )

    @focus_dim_level.setter
    def focus_dim_level(self, value: int) -> None:
        self._set_value("focus/dim_level", int(value))

    # ---- General ----
    @property
    def autostart(self) -> bool:
        return self._s.value(
            "general/autostart", DEFAULT_PREFERENCES.autostart, type=bool
        )

    @autostart.setter
    def autostart(self, value: bool) -> None:
        self._set_value("general/autostart", bool(value))

    @property
    def theme(self) -> str:
        return self._s.value("general/theme", DEFAULT_PREFERENCES.theme, type=str)

    @theme.setter
    def theme(self, value: str) -> None:
        self._set_value("general/theme", value)

    @property
    def motion_mode(self) -> str:
        value = self._s.value(
            "general/motion_mode", DEFAULT_PREFERENCES.motion_mode, type=str
        )
        return value if value in {"system", "standard", "reduced"} else "system"

    @motion_mode.setter
    def motion_mode(self, value: str) -> None:
        if value not in {"system", "standard", "reduced"}:
            raise ValueError(f"Unknown motion mode: {value}")
        self._set_value("general/motion_mode", value)

    # ---- Context-aware suppression ----
    @property
    def smart_pause_enabled(self) -> bool:
        return self._s.value(
            "context/smart_pause_enabled",
            DEFAULT_PREFERENCES.smart_pause_enabled,
            type=bool,
        )

    @smart_pause_enabled.setter
    def smart_pause_enabled(self, value: bool) -> None:
        self._set_value("context/smart_pause_enabled", bool(value))

    @property
    def fullscreen_pause_enabled(self) -> bool:
        return self._s.value(
            "context/fullscreen_pause_enabled",
            DEFAULT_PREFERENCES.fullscreen_pause_enabled,
            type=bool,
        )

    @fullscreen_pause_enabled.setter
    def fullscreen_pause_enabled(self, value: bool) -> None:
        self._set_value("context/fullscreen_pause_enabled", bool(value))

    @property
    def natural_rest_enabled(self) -> bool:
        return self._s.value(
            "context/natural_rest_enabled",
            DEFAULT_PREFERENCES.natural_rest_enabled,
            type=bool,
        )

    @natural_rest_enabled.setter
    def natural_rest_enabled(self, value: bool) -> None:
        self._set_value("context/natural_rest_enabled", bool(value))

    @property
    def app_rules(self) -> tuple[AppRule, ...]:
        raw_value = self._s.value("context/app_rules_json", "[]")
        if isinstance(raw_value, str):
            try:
                raw_rules = json.loads(raw_value)
            except (TypeError, ValueError):
                return ()
        else:
            raw_rules = raw_value
        if not isinstance(raw_rules, list):
            return ()

        rules: list[AppRule] = []
        seen: set[str] = set()
        for raw_rule in raw_rules:
            if not isinstance(raw_rule, Mapping):
                continue
            try:
                rule = _validated_app_rule(raw_rule)
            except ValueError:
                continue
            if rule["app_id"] in seen:
                continue
            seen.add(rule["app_id"])
            rules.append(rule)
            if len(rules) == 100:
                break
        return tuple(rules)

    @app_rules.setter
    def app_rules(self, value: Iterable[Mapping[str, object]]) -> None:
        rules = tuple(_validated_app_rule(rule) for rule in value)
        if len(rules) > 100:
            raise ValueError("At most 100 application rules may be stored")
        app_ids = [rule["app_id"] for rule in rules]
        if len(app_ids) != len(set(app_ids)):
            raise ValueError("Application rule app_id values must be unique")
        self._set_value(
            "context/app_rules_json",
            json.dumps(rules, ensure_ascii=True, separators=(",", ":")),
        )

    def upsert_app_rule(self, rule: Mapping[str, object]) -> None:
        normalized = _validated_app_rule(rule)
        rules = list(self.app_rules)
        for index, current in enumerate(rules):
            if current["app_id"] == normalized["app_id"]:
                rules[index] = normalized
                self.app_rules = rules
                return
        if len(rules) >= 100:
            raise ValueError("At most 100 application rules may be stored")
        rules.append(normalized)
        self.app_rules = rules

    def remove_app_rule(self, app_id: str) -> None:
        normalized = _validated_app_rule(
            {
                "app_id": app_id,
                "breaks": False,
                "focus": False,
                "filter": False,
                "dimmer": False,
            }
        )["app_id"]
        self.app_rules = tuple(
            rule for rule in self.app_rules if rule["app_id"] != normalized
        )

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
        self._set_value("general/onboarding_completed", completed)
        self._set_value("general/first_run_complete", completed)

    @property
    def latitude(self) -> float:
        # Compatibility fallback only.  ``location_configured`` determines
        # whether automation may use it.
        return self._s.value(
            "location/latitude", DEFAULT_PREFERENCES.latitude, type=float
        )

    @latitude.setter
    def latitude(self, value: float) -> None:
        self._set_value("location/latitude", float(value))

    @property
    def longitude(self) -> float:
        return self._s.value(
            "location/longitude", DEFAULT_PREFERENCES.longitude, type=float
        )

    @longitude.setter
    def longitude(self, value: float) -> None:
        self._set_value("location/longitude", float(value))

    @property
    def location_configured(self) -> bool:
        return self._s.value(
            "location/configured",
            DEFAULT_PREFERENCES.location_configured,
            type=bool,
        )

    @location_configured.setter
    def location_configured(self, value: bool) -> None:
        self._set_value("location/configured", bool(value))

    @property
    def city(self) -> str:
        return self._s.value("location/city", DEFAULT_PREFERENCES.city, type=str)

    @city.setter
    def city(self, value: str) -> None:
        self._set_value("location/city", value)

    @property
    def pet_x(self) -> int | None:
        value = self._s.value("ui/pet_x", None)
        if value in (None, ""):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @pet_x.setter
    def pet_x(self, value: int | None) -> None:
        self._set_value("ui/pet_x", "" if value is None else int(value))

    @property
    def pet_y(self) -> int | None:
        value = self._s.value("ui/pet_y", None)
        if value in (None, ""):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @pet_y.setter
    def pet_y(self, value: int | None) -> None:
        self._set_value("ui/pet_y", "" if value is None else int(value))

    # ---- Desktop companion ----
    @property
    def companion_enabled(self) -> bool:
        return self._s.value(
            'companion/enabled', DEFAULT_PREFERENCES.companion_enabled, type=bool
        )

    @companion_enabled.setter
    def companion_enabled(self, value: bool) -> None:
        self._set_value('companion/enabled', bool(value))

    @property
    def active_pet_id(self) -> str:
        raw = self._s.value(
            'companion/active_pet_id', DEFAULT_PREFERENCES.active_pet_id, type=str
        )
        try:
            return _validated_pet_id(raw)
        except ValueError:
            return DEFAULT_PREFERENCES.active_pet_id

    @active_pet_id.setter
    def active_pet_id(self, value: str) -> None:
        self._set_value('companion/active_pet_id', _validated_pet_id(value))

    @property
    def recovery_pet_id(self) -> str:
        raw = self._s.value(
            'companion/recovery_pet_id',
            DEFAULT_PREFERENCES.recovery_pet_id,
            type=str,
        )
        if not str(raw).strip():
            return ''
        try:
            return _validated_pet_id(raw)
        except ValueError:
            return ''

    @recovery_pet_id.setter
    def recovery_pet_id(self, value: str) -> None:
        raw = str(value).strip()
        self._set_value(
            'companion/recovery_pet_id',
            _validated_pet_id(raw) if raw else '',
        )

    @property
    def pet_scale_percent(self) -> int:
        value = self._s.value(
            'companion/scale_percent',
            DEFAULT_PREFERENCES.pet_scale_percent,
            type=int,
        )
        return value if 60 <= value <= 200 else DEFAULT_PREFERENCES.pet_scale_percent

    @pet_scale_percent.setter
    def pet_scale_percent(self, value: int) -> None:
        scale = int(value)
        if not 60 <= scale <= 200:
            raise ValueError('Pet scale must be between 60 and 200 percent')
        self._set_value('companion/scale_percent', scale)

    @property
    def pet_anchor_edge(self) -> str:
        edge = self._s.value(
            'companion/anchor_edge', DEFAULT_PREFERENCES.pet_anchor_edge, type=str
        )
        return edge if edge in _PET_ANCHOR_EDGES else DEFAULT_PREFERENCES.pet_anchor_edge

    @pet_anchor_edge.setter
    def pet_anchor_edge(self, value: str) -> None:
        edge = str(value).strip().lower()
        if edge not in _PET_ANCHOR_EDGES:
            raise ValueError('Unknown pet anchor edge')
        self._set_value('companion/anchor_edge', edge)

    @property
    def pet_anchor_offset(self) -> int:
        value = self._s.value(
            'companion/anchor_offset',
            DEFAULT_PREFERENCES.pet_anchor_offset,
            type=int,
        )
        return value if 0 <= value <= 10000 else DEFAULT_PREFERENCES.pet_anchor_offset

    @pet_anchor_offset.setter
    def pet_anchor_offset(self, value: int) -> None:
        offset = int(value)
        if not 0 <= offset <= 10000:
            raise ValueError('Pet anchor offset is outside the supported range')
        self._set_value('companion/anchor_offset', offset)

    @property
    def follow_active_monitor(self) -> bool:
        return self._s.value(
            'companion/follow_active_monitor',
            DEFAULT_PREFERENCES.follow_active_monitor,
            type=bool,
        )

    @follow_active_monitor.setter
    def follow_active_monitor(self, value: bool) -> None:
        self._set_value('companion/follow_active_monitor', bool(value))

    @property
    def window_avoidance_enabled(self) -> bool:
        return self._s.value(
            'companion/window_avoidance_enabled',
            DEFAULT_PREFERENCES.window_avoidance_enabled,
            type=bool,
        )

    @window_avoidance_enabled.setter
    def window_avoidance_enabled(self, value: bool) -> None:
        self._set_value('companion/window_avoidance_enabled', bool(value))

    @property
    def companion_sound_enabled(self) -> bool:
        return self._s.value(
            'companion/sound_enabled',
            DEFAULT_PREFERENCES.companion_sound_enabled,
            type=bool,
        )

    @companion_sound_enabled.setter
    def companion_sound_enabled(self, value: bool) -> None:
        self._set_value('companion/sound_enabled', bool(value))

    @property
    def hourly_chime_enabled(self) -> bool:
        return self._s.value(
            'companion/hourly_chime_enabled',
            DEFAULT_PREFERENCES.hourly_chime_enabled,
            type=bool,
        )

    @hourly_chime_enabled.setter
    def hourly_chime_enabled(self, value: bool) -> None:
        self._set_value('companion/hourly_chime_enabled', bool(value))

    @property
    def quiet_hours_start(self) -> str:
        value = self._s.value(
            'companion/quiet_hours_start',
            DEFAULT_PREFERENCES.quiet_hours_start,
            type=str,
        )
        return value if _CLOCK_PATTERN.fullmatch(value) else DEFAULT_PREFERENCES.quiet_hours_start

    @quiet_hours_start.setter
    def quiet_hours_start(self, value: str) -> None:
        clock = str(value).strip()
        if not _CLOCK_PATTERN.fullmatch(clock):
            raise ValueError('Quiet-hours start must use HH:MM')
        self._set_value('companion/quiet_hours_start', clock)

    @property
    def quiet_hours_end(self) -> str:
        value = self._s.value(
            'companion/quiet_hours_end',
            DEFAULT_PREFERENCES.quiet_hours_end,
            type=str,
        )
        return value if _CLOCK_PATTERN.fullmatch(value) else DEFAULT_PREFERENCES.quiet_hours_end

    @quiet_hours_end.setter
    def quiet_hours_end(self, value: str) -> None:
        clock = str(value).strip()
        if not _CLOCK_PATTERN.fullmatch(clock):
            raise ValueError('Quiet-hours end must use HH:MM')
        self._set_value('companion/quiet_hours_end', clock)

    @property
    def quick_actions(self) -> tuple[str, ...]:
        raw = self._s.value('companion/quick_actions_json', '[]')
        try:
            decoded = json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, ValueError):
            decoded = ()
        if not isinstance(decoded, (list, tuple)):
            return DEFAULT_PREFERENCES.quick_actions
        result = tuple(
            dict.fromkeys(
                str(item).strip().lower()
                for item in decoded
                if str(item).strip().lower() in _QUICK_ACTIONS
            )
        )
        return result or DEFAULT_PREFERENCES.quick_actions

    @quick_actions.setter
    def quick_actions(self, value: Iterable[str]) -> None:
        normalized = tuple(
            dict.fromkeys(str(item).strip().lower() for item in value)
        )
        if not 1 <= len(normalized) <= 4:
            raise ValueError('Choose between one and four quick actions')
        if any(item not in _QUICK_ACTIONS for item in normalized):
            raise ValueError('Unknown companion quick action')
        self._set_value(
            'companion/quick_actions_json',
            json.dumps(normalized, ensure_ascii=True, separators=(',', ':')),
        )

    @property
    def pet_preferences(self) -> dict[str, dict[str, str]]:
        raw = self._s.value('companion/pet_preferences_json', '{}')
        try:
            decoded = json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, ValueError):
            return {}
        if not isinstance(decoded, Mapping):
            return {}
        result: dict[str, dict[str, str]] = {}
        for raw_pet_id, raw_slots in tuple(decoded.items())[:32]:
            if not isinstance(raw_slots, Mapping):
                continue
            try:
                pet_id = _validated_pet_id(raw_pet_id)
            except ValueError:
                continue
            slots: dict[str, str] = {}
            for raw_slot, raw_item in raw_slots.items():
                slot = str(raw_slot)
                if slot not in _PET_ACCESSORY_SLOTS:
                    continue
                try:
                    slots[slot] = _validated_item_id(raw_item)
                except ValueError:
                    continue
            result[pet_id] = slots
        return result

    @pet_preferences.setter
    def pet_preferences(self, value: Mapping[str, Mapping[str, object]]) -> None:
        if len(value) > 32:
            raise ValueError('At most 32 pet preference entries may be stored')
        normalized: dict[str, dict[str, str]] = {}
        for raw_pet_id, raw_slots in value.items():
            pet_id = _validated_pet_id(raw_pet_id)
            if not isinstance(raw_slots, Mapping):
                raise ValueError('Pet preferences must contain slot mappings')
            slots: dict[str, str] = {}
            for raw_slot, raw_item in raw_slots.items():
                slot = str(raw_slot)
                if slot not in _PET_ACCESSORY_SLOTS:
                    raise ValueError('Unknown pet accessory slot')
                slots[slot] = _validated_item_id(raw_item)
            normalized[pet_id] = slots
        self._set_value(
            'companion/pet_preferences_json',
            json.dumps(normalized, ensure_ascii=True, separators=(',', ':')),
        )

    @property
    def app_prop_rules(self) -> tuple[AppPropRule, ...]:
        raw = self._s.value('companion/app_prop_rules_json', '[]')
        try:
            decoded = json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, ValueError):
            return ()
        if not isinstance(decoded, list):
            return ()
        result: list[AppPropRule] = []
        seen: set[str] = set()
        for item in decoded:
            if not isinstance(item, Mapping):
                continue
            try:
                rule = _validated_app_prop_rule(item)
            except ValueError:
                continue
            if rule['app_id'] in seen:
                continue
            seen.add(rule['app_id'])
            result.append(rule)
            if len(result) == 100:
                break
        return tuple(result)

    @app_prop_rules.setter
    def app_prop_rules(self, value: Iterable[Mapping[str, object]]) -> None:
        rules = tuple(_validated_app_prop_rule(rule) for rule in value)
        if len(rules) > 100:
            raise ValueError('At most 100 application prop rules may be stored')
        app_ids = [rule['app_id'] for rule in rules]
        if len(app_ids) != len(set(app_ids)):
            raise ValueError('Application prop rule app_id values must be unique')
        self._set_value(
            'companion/app_prop_rules_json',
            json.dumps(rules, ensure_ascii=True, separators=(',', ':')),
        )

    @property
    def weather_enabled(self) -> bool:
        return self._s.value(
            'weather/enabled', DEFAULT_PREFERENCES.weather_enabled, type=bool
        )

    @weather_enabled.setter
    def weather_enabled(self, value: bool) -> None:
        self._set_value('weather/enabled', bool(value))

    @property
    def holiday_pack(self) -> str:
        value = self._s.value(
            'holiday/pack', DEFAULT_PREFERENCES.holiday_pack, type=str
        )
        return value if value in {'zh-CN', 'none'} else DEFAULT_PREFERENCES.holiday_pack

    @holiday_pack.setter
    def holiday_pack(self, value: str) -> None:
        pack = str(value)
        if pack not in {'zh-CN', 'none'}:
            raise ValueError('Unknown holiday pack')
        self._set_value('holiday/pack', pack)

    @property
    def break_rest_scene(self) -> str:
        value = self._s.value(
            'break/rest_scene', DEFAULT_PREFERENCES.rest_scene, type=str
        )
        return value if value in _REST_SCENES else DEFAULT_PREFERENCES.rest_scene

    @break_rest_scene.setter
    def break_rest_scene(self, value: str) -> None:
        scene = str(value).strip().lower()
        if scene not in _REST_SCENES:
            raise ValueError('Unknown rest scene')
        self._set_value('break/rest_scene', scene)

    # ---- Hotkeys ----
    @property
    def hotkey_filter(self) -> str:
        return self._s.value(
            "hotkeys/filter", DEFAULT_PREFERENCES.hotkey_filter, type=str
        )

    @hotkey_filter.setter
    def hotkey_filter(self, value: str) -> None:
        self._set_value("hotkeys/filter", value)

    @property
    def hotkey_break(self) -> str:
        return self._s.value(
            "hotkeys/break", DEFAULT_PREFERENCES.hotkey_break, type=str
        )

    @hotkey_break.setter
    def hotkey_break(self, value: str) -> None:
        self._set_value("hotkeys/break", value)

    @property
    def hotkey_dimmer(self) -> str:
        return self._s.value(
            "hotkeys/dimmer", DEFAULT_PREFERENCES.hotkey_dimmer, type=str
        )

    @hotkey_dimmer.setter
    def hotkey_dimmer(self, value: str) -> None:
        self._set_value("hotkeys/dimmer", value)

    @property
    def hotkey_focus(self) -> str:
        return self._s.value(
            "hotkeys/focus", DEFAULT_PREFERENCES.hotkey_focus, type=str
        )

    @hotkey_focus.setter
    def hotkey_focus(self, value: str) -> None:
        self._set_value("hotkeys/focus", value)

    # ---- Preset ----
    @property
    def current_preset(self) -> str:
        return self._s.value(
            "preset/current", DEFAULT_PREFERENCES.current_preset, type=str
        )

    @current_preset.setter
    def current_preset(self, value: str) -> None:
        self._set_value("preset/current", value)

    # ---- Temporary global pause ----
    @property
    def global_pause_mode(self) -> str:
        return self._s.value(
            "pause/mode", DEFAULT_PREFERENCES.global_pause_mode, type=str
        )

    @global_pause_mode.setter
    def global_pause_mode(self, value: str) -> None:
        self._set_value("pause/mode", value)

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
        self._set_value("pause/until", "" if value is None else float(value))

    def snapshot(self) -> dict[str, object]:
        """Return a complete in-process snapshot for command rollback."""
        return _snapshot_store(self._s)

    def restore_snapshot(self, snapshot: Mapping[str, object]) -> None:
        """Restore and persist a snapshot, checking the backend result."""
        if self._read_only:
            raise SettingsReadOnlyError(
                f"Cannot restore newer settings schema v{self._stored_schema_version}"
            )
        _restore_store(self._s, snapshot)
        _sync_store_checked(self._s)

    def sync_checked(self) -> None:
        """Persist pending writes and raise when QSettings reports an error."""
        if self._read_only:
            raise SettingsReadOnlyError(
                f"Cannot sync newer settings schema v{self._stored_schema_version}"
            )
        _sync_store_checked(self._s)

    def sync(self) -> None:
        """Compatibility spelling for checked persistence."""
        self.sync_checked()

    @contextmanager
    def transaction(self) -> Iterator[Settings]:
        """Commit preference writes atomically or restore the prior snapshot."""
        if self._read_only:
            raise SettingsReadOnlyError(
                f"Cannot update newer settings schema v{self._stored_schema_version}"
            )
        snapshot = self.snapshot()
        try:
            yield self
            self.sync_checked()
        except Exception:
            try:
                self.restore_snapshot(snapshot)
            except Exception as rollback_error:
                raise SettingsTransactionError(
                    "Settings transaction failed and rollback could not be persisted"
                ) from rollback_error
            raise

    def reset(self) -> None:
        """Clear user settings and recreate a fresh schema-v6 marker."""
        if self._read_only:
            raise SettingsReadOnlyError(
                f"Cannot reset newer settings schema v{self._stored_schema_version}"
            )
        with self.transaction():
            self._s.clear()
            self._set_value("meta/schema_version", SCHEMA_VERSION)


class PreferencesRepository(Settings):
    """Named configuration boundary used by the application layer.

    ``Settings`` remains as a compatibility name for v0.1-v0.2 integrations.
    """
