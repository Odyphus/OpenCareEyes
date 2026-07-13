"""QSettings-based configuration management and schema migrations."""

from __future__ import annotations

import os
import json
from collections.abc import Iterable, Mapping
from enum import Enum
from typing import Any, TypedDict

from PySide6.QtCore import QSettings

from opencareyes.config.defaults import DEFAULT_PREFERENCES, LEGACY_V2_PREFERENCES
from opencareyes.constants import APP_NAME, ORG_NAME


SCHEMA_VERSION = 3


class SettingsReadOnlyError(RuntimeError):
    """Raised when this build cannot safely write a newer settings schema."""


class SettingsMigrationError(RuntimeError):
    """Raised after a failed migration has been rolled back."""


class AppRule(TypedDict):
    app_id: str
    breaks: bool
    focus: bool
    filter: bool
    dimmer: bool


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
            self._sync_checked()
        except Exception as exc:
            self._restore(snapshot)
            raise SettingsMigrationError(
                f"Unable to migrate settings to schema v{SCHEMA_VERSION}; "
                "the previous settings were restored"
            ) from exc
        return version, False

    def _snapshot(self) -> dict[str, object]:
        try:
            keys = tuple(self._store.allKeys() or ())
        except (AttributeError, TypeError):
            keys = ()
        return {str(key): self._store.value(key, None) for key in keys}

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

    def _sync_checked(self) -> None:
        sync = getattr(self._store, "sync", None)
        if callable(sync):
            sync()
        status_method = getattr(self._store, "status", None)
        if not callable(status_method):
            return
        status = status_method()
        if (type(status) is int and status != 0) or (
            isinstance(status, Enum) and status.name != "NoError"
        ):
            raise OSError(f"Settings backend sync failed: {status}")

    def _restore(self, snapshot: Mapping[str, object]) -> None:
        self._store.clear()
        for key, value in snapshot.items():
            self._store.setValue(key, value)
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
        return self._s.value(
            "break/work_duration", DEFAULT_PREFERENCES.work_duration, type=int
        )

    @work_duration.setter
    def work_duration(self, value: int) -> None:
        self._set_value("break/work_duration", int(value))

    @property
    def break_duration(self) -> int:
        return self._s.value(
            "break/break_duration", DEFAULT_PREFERENCES.break_duration, type=int
        )

    @break_duration.setter
    def break_duration(self, value: int) -> None:
        self._set_value("break/break_duration", int(value))

    @property
    def break_mode(self) -> str:
        return self._s.value(
            "break/mode", DEFAULT_PREFERENCES.break_mode, type=str
        )

    @break_mode.setter
    def break_mode(self, value: str) -> None:
        self._set_value("break/mode", value)

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

    def sync(self) -> None:
        self._s.sync()

    def reset(self) -> None:
        """Clear user settings and recreate a fresh schema-v3 marker."""
        if self._read_only:
            raise SettingsReadOnlyError(
                f"Cannot reset newer settings schema v{self._stored_schema_version}"
            )
        self._s.clear()
        self._set_value("meta/schema_version", SCHEMA_VERSION)
        self._s.sync()


class PreferencesRepository(Settings):
    """Named configuration boundary used by the v0.3 application layer.

    ``Settings`` remains as a compatibility name for v0.1-v0.2 integrations.
    """
