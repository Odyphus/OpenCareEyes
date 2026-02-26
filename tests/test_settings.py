"""Unit tests for Settings class."""

import pytest
from unittest.mock import patch, MagicMock

from opencareyes.constants import (
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


@pytest.fixture
def mock_qsettings():
    """Patch QSettings so tests don't touch the real registry."""
    store = {}

    def fake_value(key, default=None, type=None):
        return store.get(key, default)

    def fake_set(key, value):
        store[key] = value

    with patch("opencareyes.config.settings.QSettings") as mock_cls:
        instance = MagicMock()
        instance.value.side_effect = fake_value
        instance.setValue.side_effect = fake_set
        mock_cls.return_value = instance
        yield instance, store


@pytest.fixture
def settings(mock_qsettings):
    from opencareyes.config.settings import Settings
    return Settings()


class TestSettingsDefaults:
    def test_filter_enabled_default(self, settings):
        assert settings.filter_enabled is False

    def test_color_temperature_default(self, settings):
        assert settings.color_temperature == TEMP_DEFAULT

    def test_filter_schedule_default(self, settings):
        assert settings.filter_schedule_enabled is False

    def test_dimmer_enabled_default(self, settings):
        assert settings.dimmer_enabled is False

    def test_dim_level_default(self, settings):
        assert settings.dim_level == DIM_DEFAULT

    def test_break_enabled_default(self, settings):
        assert settings.break_enabled is False

    def test_work_duration_default(self, settings):
        assert settings.work_duration == WORK_DURATION_DEFAULT

    def test_break_duration_default(self, settings):
        assert settings.break_duration == BREAK_DURATION_DEFAULT

    def test_break_mode_default(self, settings):
        assert settings.break_mode == "pomodoro"

    def test_micro_break_interval_default(self, settings):
        assert settings.micro_break_interval == MICRO_BREAK_INTERVAL_DEFAULT

    def test_micro_break_duration_default(self, settings):
        assert settings.micro_break_duration == MICRO_BREAK_DURATION_DEFAULT

    def test_force_break_default(self, settings):
        assert settings.force_break is True

    def test_focus_enabled_default(self, settings):
        assert settings.focus_enabled is False

    def test_focus_dim_level_default(self, settings):
        assert settings.focus_dim_level == FOCUS_DIM_DEFAULT

    def test_autostart_default(self, settings):
        assert settings.autostart is False

    def test_theme_default(self, settings):
        assert settings.theme == "dark"

    def test_hotkey_defaults(self, settings):
        assert settings.hotkey_filter == HOTKEY_TOGGLE_FILTER
        assert settings.hotkey_break == HOTKEY_TOGGLE_BREAK
        assert settings.hotkey_dimmer == HOTKEY_TOGGLE_DIMMER
        assert settings.hotkey_focus == HOTKEY_TOGGLE_FOCUS


class TestSettingsSetGet:
    def test_set_filter_enabled(self, settings, mock_qsettings):
        settings.filter_enabled = True
        _, store = mock_qsettings
        assert store["filter/enabled"] is True

    def test_set_color_temperature(self, settings, mock_qsettings):
        settings.color_temperature = 3400
        _, store = mock_qsettings
        assert store["filter/temperature"] == 3400

    def test_set_dim_level(self, settings, mock_qsettings):
        settings.dim_level = 100
        _, store = mock_qsettings
        assert store["dimmer/level"] == 100

    def test_set_break_mode(self, settings, mock_qsettings):
        settings.break_mode = "20-20-20"
        _, store = mock_qsettings
        assert store["break/mode"] == "20-20-20"

    def test_set_theme(self, settings, mock_qsettings):
        settings.theme = "light"
        _, store = mock_qsettings
        assert store["general/theme"] == "light"

    def test_set_location(self, settings, mock_qsettings):
        settings.latitude = 31.23
        settings.longitude = 121.47
        _, store = mock_qsettings
        assert store["location/latitude"] == 31.23
        assert store["location/longitude"] == 121.47


class TestSettingsPropertyTypes:
    def test_filter_enabled_is_bool(self, settings):
        assert isinstance(settings.filter_enabled, bool)

    def test_color_temperature_is_int(self, settings):
        assert isinstance(settings.color_temperature, int)

    def test_dim_level_is_int(self, settings):
        assert isinstance(settings.dim_level, int)

    def test_break_mode_is_str(self, settings):
        assert isinstance(settings.break_mode, str)

    def test_theme_is_str(self, settings):
        assert isinstance(settings.theme, str)

    def test_latitude_is_float(self, settings):
        assert isinstance(settings.latitude, float)

    def test_longitude_is_float(self, settings):
        assert isinstance(settings.longitude, float)

    def test_force_break_is_bool(self, settings):
        assert isinstance(settings.force_break, bool)
