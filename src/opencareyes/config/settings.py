"""QSettings-based configuration management."""

from PySide6.QtCore import QSettings

from opencareyes.constants import (
    APP_NAME,
    ORG_NAME,
    TEMP_DEFAULT,
    DIM_DEFAULT,
    WORK_DURATION_DEFAULT,
    BREAK_DURATION_DEFAULT,
    MICRO_BREAK_INTERVAL_DEFAULT,
    MICRO_BREAK_DURATION_DEFAULT,
    FOCUS_DIM_DEFAULT,
    HOTKEY_TOGGLE_FILTER,
    HOTKEY_TOGGLE_BREAK,
    HOTKEY_TOGGLE_DIMMER,
    HOTKEY_TOGGLE_FOCUS,
)


class Settings:
    """Thin wrapper around QSettings with typed accessors."""

    def __init__(self):
        self._s = QSettings(ORG_NAME, APP_NAME)

    # ---- Blue light filter ----
    @property
    def filter_enabled(self) -> bool:
        return self._s.value("filter/enabled", False, type=bool)

    @filter_enabled.setter
    def filter_enabled(self, v: bool):
        self._s.setValue("filter/enabled", v)

    @property
    def color_temperature(self) -> int:
        return self._s.value("filter/temperature", TEMP_DEFAULT, type=int)

    @color_temperature.setter
    def color_temperature(self, v: int):
        self._s.setValue("filter/temperature", v)

    @property
    def filter_schedule_enabled(self) -> bool:
        return self._s.value("filter/schedule_enabled", False, type=bool)

    @filter_schedule_enabled.setter
    def filter_schedule_enabled(self, v: bool):
        self._s.setValue("filter/schedule_enabled", v)

    # ---- Screen dimmer ----
    @property
    def dimmer_enabled(self) -> bool:
        return self._s.value("dimmer/enabled", False, type=bool)

    @dimmer_enabled.setter
    def dimmer_enabled(self, v: bool):
        self._s.setValue("dimmer/enabled", v)

    @property
    def dim_level(self) -> int:
        return self._s.value("dimmer/level", DIM_DEFAULT, type=int)

    @dim_level.setter
    def dim_level(self, v: int):
        self._s.setValue("dimmer/level", v)

    # ---- Break reminder ----
    @property
    def break_enabled(self) -> bool:
        return self._s.value("break/enabled", False, type=bool)

    @break_enabled.setter
    def break_enabled(self, v: bool):
        self._s.setValue("break/enabled", v)

    @property
    def work_duration(self) -> int:
        return self._s.value("break/work_duration", WORK_DURATION_DEFAULT, type=int)

    @work_duration.setter
    def work_duration(self, v: int):
        self._s.setValue("break/work_duration", v)

    @property
    def break_duration(self) -> int:
        return self._s.value("break/break_duration", BREAK_DURATION_DEFAULT, type=int)

    @break_duration.setter
    def break_duration(self, v: int):
        self._s.setValue("break/break_duration", v)

    @property
    def break_mode(self) -> str:
        return self._s.value("break/mode", "pomodoro", type=str)

    @break_mode.setter
    def break_mode(self, v: str):
        self._s.setValue("break/mode", v)

    @property
    def micro_break_interval(self) -> int:
        return self._s.value("break/micro_interval", MICRO_BREAK_INTERVAL_DEFAULT, type=int)

    @micro_break_interval.setter
    def micro_break_interval(self, v: int):
        self._s.setValue("break/micro_interval", v)

    @property
    def micro_break_duration(self) -> int:
        return self._s.value("break/micro_duration", MICRO_BREAK_DURATION_DEFAULT, type=int)

    @micro_break_duration.setter
    def micro_break_duration(self, v: int):
        self._s.setValue("break/micro_duration", v)

    @property
    def force_break(self) -> bool:
        return self._s.value("break/force", True, type=bool)

    @force_break.setter
    def force_break(self, v: bool):
        self._s.setValue("break/force", v)

    # ---- Focus mode ----
    @property
    def focus_enabled(self) -> bool:
        return self._s.value("focus/enabled", False, type=bool)

    @focus_enabled.setter
    def focus_enabled(self, v: bool):
        self._s.setValue("focus/enabled", v)

    @property
    def focus_dim_level(self) -> int:
        return self._s.value("focus/dim_level", FOCUS_DIM_DEFAULT, type=int)

    @focus_dim_level.setter
    def focus_dim_level(self, v: int):
        self._s.setValue("focus/dim_level", v)

    # ---- General ----
    @property
    def autostart(self) -> bool:
        return self._s.value("general/autostart", False, type=bool)

    @autostart.setter
    def autostart(self, v: bool):
        self._s.setValue("general/autostart", v)

    @property
    def theme(self) -> str:
        return self._s.value("general/theme", "dark", type=str)

    @theme.setter
    def theme(self, v: str):
        self._s.setValue("general/theme", v)

    @property
    def latitude(self) -> float:
        return self._s.value("location/latitude", 39.9, type=float)

    @latitude.setter
    def latitude(self, v: float):
        self._s.setValue("location/latitude", v)

    @property
    def longitude(self) -> float:
        return self._s.value("location/longitude", 116.4, type=float)

    @longitude.setter
    def longitude(self, v: float):
        self._s.setValue("location/longitude", v)

    # ---- Hotkeys ----
    @property
    def hotkey_filter(self) -> str:
        return self._s.value("hotkeys/filter", HOTKEY_TOGGLE_FILTER, type=str)

    @hotkey_filter.setter
    def hotkey_filter(self, v: str):
        self._s.setValue("hotkeys/filter", v)

    @property
    def hotkey_break(self) -> str:
        return self._s.value("hotkeys/break", HOTKEY_TOGGLE_BREAK, type=str)

    @hotkey_break.setter
    def hotkey_break(self, v: str):
        self._s.setValue("hotkeys/break", v)

    @property
    def hotkey_dimmer(self) -> str:
        return self._s.value("hotkeys/dimmer", HOTKEY_TOGGLE_DIMMER, type=str)

    @hotkey_dimmer.setter
    def hotkey_dimmer(self, v: str):
        self._s.setValue("hotkeys/dimmer", v)

    @property
    def hotkey_focus(self) -> str:
        return self._s.value("hotkeys/focus", HOTKEY_TOGGLE_FOCUS, type=str)

    @hotkey_focus.setter
    def hotkey_focus(self, v: str):
        self._s.setValue("hotkeys/focus", v)

    # ---- Preset ----
    @property
    def current_preset(self) -> str:
        return self._s.value("preset/current", "custom", type=str)

    @current_preset.setter
    def current_preset(self, v: str):
        self._s.setValue("preset/current", v)

    def sync(self):
        self._s.sync()
