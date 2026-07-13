"""Canonical preference defaults and legacy migration values."""

from __future__ import annotations

from dataclasses import dataclass

from opencareyes.constants import (
    DIM_DEFAULT,
    FOCUS_DIM_DEFAULT,
    HOTKEY_TOGGLE_BREAK,
    HOTKEY_TOGGLE_DIMMER,
    HOTKEY_TOGGLE_FILTER,
    HOTKEY_TOGGLE_FOCUS,
    MICRO_BREAK_DURATION_DEFAULT,
    MICRO_BREAK_INTERVAL_DEFAULT,
    TEMP_DEFAULT,
)


@dataclass(frozen=True)
class DefaultPreferences:
    """Defaults used when a preference has not been persisted."""

    filter_enabled: bool = False
    color_temperature: int = TEMP_DEFAULT
    schedule_enabled: bool = False
    schedule_mode: str = "fixed"
    schedule_on_time: str = "19:00"
    schedule_off_time: str = "07:30"
    schedule_days: tuple[int, ...] = (0, 1, 2, 3, 4)
    dimmer_enabled: bool = False
    dim_level: int = DIM_DEFAULT
    break_enabled: bool = False
    break_mode: str = "20-20-20"
    work_duration: int = 20 * 60
    break_duration: int = 20
    micro_break_interval: int = MICRO_BREAK_INTERVAL_DEFAULT
    micro_break_duration: int = MICRO_BREAK_DURATION_DEFAULT
    force_break: bool = False
    break_countdown_display: str = "tray"
    focus_enabled: bool = False
    focus_dim_level: int = FOCUS_DIM_DEFAULT
    autostart: bool = False
    theme: str = "system"
    motion_mode: str = "system"
    smart_pause_enabled: bool = True
    fullscreen_pause_enabled: bool = True
    natural_rest_enabled: bool = True
    latitude: float = 39.9
    longitude: float = 116.4
    location_configured: bool = False
    city: str = ""
    hotkey_filter: str = HOTKEY_TOGGLE_FILTER
    hotkey_break: str = HOTKEY_TOGGLE_BREAK
    hotkey_dimmer: str = HOTKEY_TOGGLE_DIMMER
    hotkey_focus: str = HOTKEY_TOGGLE_FOCUS
    current_preset: str = "custom"
    global_pause_mode: str = "none"


DEFAULT_PREFERENCES = DefaultPreferences()

# Missing values from an existing schema-v2 profile must keep the effective
# defaults of v0.2.1.  The v2 -> v3 migration materializes these values before
# the new-install defaults above become active.
LEGACY_V2_PREFERENCES = DefaultPreferences(
    schedule_mode="sun",
    schedule_off_time="07:00",
    schedule_days=(0, 1, 2, 3, 4, 5, 6),
    break_mode="pomodoro",
    work_duration=45 * 60,
    break_duration=3 * 60,
)

