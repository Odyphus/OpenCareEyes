"""Unit tests for Settings class."""

from unittest.mock import MagicMock, patch

import pytest

from opencareyes.config.defaults import DEFAULT_PREFERENCES
from opencareyes.config.settings import SettingsMigrationError, SettingsReadOnlyError


class MemoryStore:
    def __init__(self, values=None, *, fail_sync_count=0, fail_set_key=None):
        self.values = dict(values or {})
        self.fail_sync_count = fail_sync_count
        self.fail_set_key = fail_set_key
        self.writes = []

    def value(self, key, default=None, type=None):
        value = self.values.get(key, default)
        if type is not None and value is not None:
            return type(value)
        return value

    def setValue(self, key, value):
        if key == self.fail_set_key:
            self.fail_set_key = None
            raise OSError("simulated write failure")
        self.values[key] = value
        self.writes.append((key, value))

    def allKeys(self):
        return list(self.values)

    def sync(self):
        if self.fail_sync_count:
            self.fail_sync_count -= 1
            raise OSError("simulated sync failure")

    def clear(self):
        self.values.clear()


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
        assert settings.color_temperature == DEFAULT_PREFERENCES.color_temperature

    def test_filter_schedule_default(self, settings):
        assert settings.filter_schedule_enabled is False

    def test_dimmer_enabled_default(self, settings):
        assert settings.dimmer_enabled is False

    def test_dim_level_default(self, settings):
        assert settings.dim_level == DEFAULT_PREFERENCES.dim_level

    def test_break_enabled_default(self, settings):
        assert settings.break_enabled is False

    def test_work_duration_default(self, settings):
        assert settings.work_duration == 20 * 60

    def test_break_duration_default(self, settings):
        assert settings.break_duration == 20

    def test_break_mode_default(self, settings):
        assert settings.break_mode == "20-20-20"

    def test_micro_break_interval_default(self, settings):
        assert (
            settings.micro_break_interval
            == DEFAULT_PREFERENCES.micro_break_interval
        )

    def test_micro_break_duration_default(self, settings):
        assert (
            settings.micro_break_duration
            == DEFAULT_PREFERENCES.micro_break_duration
        )

    def test_force_break_default(self, settings):
        assert settings.force_break is False

    def test_break_countdown_display_default(self, settings):
        assert settings.break_countdown_display == "tray"

    def test_focus_enabled_default(self, settings):
        assert settings.focus_enabled is False

    def test_focus_dim_level_default(self, settings):
        assert settings.focus_dim_level == DEFAULT_PREFERENCES.focus_dim_level

    def test_autostart_default(self, settings):
        assert settings.autostart is False

    def test_theme_default(self, settings):
        assert settings.theme == "system"

    def test_hotkey_defaults(self, settings):
        assert settings.hotkey_filter == DEFAULT_PREFERENCES.hotkey_filter
        assert settings.hotkey_break == DEFAULT_PREFERENCES.hotkey_break
        assert settings.hotkey_dimmer == DEFAULT_PREFERENCES.hotkey_dimmer
        assert settings.hotkey_focus == DEFAULT_PREFERENCES.hotkey_focus

    def test_v3_context_defaults(self, settings):
        assert settings.smart_pause_enabled is True
        assert settings.fullscreen_pause_enabled is True
        assert settings.natural_rest_enabled is True
        assert settings.motion_mode == "system"
        assert settings.app_rules == ()

    def test_v3_schedule_defaults(self, settings):
        assert settings.schedule_mode == "fixed"
        assert settings.schedule_on_time == "19:00"
        assert settings.schedule_off_time == "07:30"
        assert settings.schedule_days == (0, 1, 2, 3, 4)


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

    def test_set_break_countdown_display(self, settings, mock_qsettings):
        settings.break_countdown_display = "floating"
        _, store = mock_qsettings
        assert store["break/countdown_display"] == "floating"

    def test_reject_invalid_break_countdown_display(self, settings):
        with pytest.raises(ValueError):
            settings.break_countdown_display = "always"

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


def test_environment_can_select_isolated_ini_backend(monkeypatch, tmp_path):
    from opencareyes.config.settings import Settings

    path = tmp_path / "opencareyes-test.ini"
    monkeypatch.setenv("OPENCAREYES_SETTINGS_PATH", str(path))
    first = Settings()
    first.theme = "light"
    first.sync()

    second = Settings()
    assert second.theme == "light"
    assert path.exists()


def test_empty_store_migrates_to_v3_with_new_install_defaults():
    from opencareyes.config.settings import Settings

    store = MemoryStore()
    settings = Settings(store)

    assert store.values == {"meta/schema_version": 3}
    assert settings.stored_schema_version == 3
    assert settings.read_only is False
    assert settings.break_mode == "20-20-20"
    assert settings.schedule_off_time == "07:30"


def test_v1_migrates_in_order_and_preserves_legacy_effective_defaults():
    from opencareyes.config.settings import Settings

    store = MemoryStore({"filter/enabled": True})
    settings = Settings(store)

    assert settings.stored_schema_version == 3
    assert settings.onboarding_completed is True
    assert settings.break_mode == "pomodoro"
    assert settings.work_duration == 45 * 60
    assert settings.break_duration == 3 * 60
    assert settings.schedule_mode == "sun"
    assert settings.schedule_off_time == "07:00"
    assert settings.schedule_days == (0, 1, 2, 3, 4, 5, 6)


def test_v2_migration_preserves_explicit_values_and_is_idempotent():
    from opencareyes.config.settings import Settings

    store = MemoryStore(
        {
            "meta/schema_version": 2,
            "general/theme": "dark",
            "break/work_duration": 900,
            "automation/off_time": "06:30",
        }
    )
    settings = Settings(store)
    writes_after_first_migration = tuple(store.writes)

    assert settings.theme == "dark"
    assert settings.work_duration == 900
    assert settings.schedule_off_time == "06:30"

    store.writes.clear()
    second = Settings(store)
    assert second.stored_schema_version == 3
    assert store.writes == []
    assert writes_after_first_migration


def test_schema_marker_only_is_treated_as_an_existing_profile():
    from opencareyes.config.settings import Settings

    settings = Settings(MemoryStore({"meta/schema_version": 2}))

    assert settings.break_mode == "pomodoro"
    assert settings.work_duration == 45 * 60
    assert settings.break_duration == 3 * 60
    assert settings.schedule_off_time == "07:00"
    assert settings.schedule_days == (0, 1, 2, 3, 4, 5, 6)


def test_preferences_repository_keeps_settings_compatibility():
    from opencareyes.config.settings import PreferencesRepository, Settings

    repository = PreferencesRepository(MemoryStore())

    assert isinstance(repository, Settings)
    assert repository.stored_schema_version == 3


def test_migration_sync_failure_restores_exact_snapshot():
    from opencareyes.config.settings import Settings

    original = {"meta/schema_version": 2, "general/theme": "dark"}
    store = MemoryStore(original, fail_sync_count=1)

    with pytest.raises(SettingsMigrationError, match="previous settings were restored"):
        Settings(store)

    assert store.values == original


def test_migration_write_failure_restores_exact_snapshot():
    from opencareyes.config.settings import Settings

    original = {"meta/schema_version": 2, "general/theme": "dark"}
    store = MemoryStore(original, fail_set_key="break/mode")

    with pytest.raises(SettingsMigrationError):
        Settings(store)

    assert store.values == original


def test_future_schema_is_read_only_and_never_migrated():
    from opencareyes.config.settings import Settings

    original = {"meta/schema_version": 9, "general/theme": "future"}
    store = MemoryStore(original)
    settings = Settings(store)

    assert settings.read_only is True
    assert settings.stored_schema_version == 9
    assert settings.schema_version == 9
    assert store.writes == []
    with pytest.raises(SettingsReadOnlyError, match="schema v9"):
        settings.theme = "dark"
    with pytest.raises(SettingsReadOnlyError, match="schema v9"):
        settings.reset()
    assert store.values == original


def test_v3_accessors_and_application_rules_round_trip():
    from opencareyes.config.settings import Settings

    store = MemoryStore()
    settings = Settings(store)
    settings.smart_pause_enabled = False
    settings.fullscreen_pause_enabled = False
    settings.natural_rest_enabled = False
    settings.motion_mode = "reduced"
    settings.app_rules = (
        {
            "app_id": "POWERPNT.EXE",
            "breaks": True,
            "focus": True,
            "filter": False,
            "dimmer": False,
        },
    )

    assert settings.smart_pause_enabled is False
    assert settings.fullscreen_pause_enabled is False
    assert settings.natural_rest_enabled is False
    assert settings.motion_mode == "reduced"
    assert settings.app_rules == (
        {
            "app_id": "powerpnt.exe",
            "breaks": True,
            "focus": True,
            "filter": False,
            "dimmer": False,
        },
    )
    assert store.values["context/app_rules_json"].startswith("[{")


@pytest.mark.parametrize(
    "rule",
    [
        {
            "app_id": r"C:\\Windows\\powerpnt.exe",
            "breaks": True,
            "focus": True,
            "filter": False,
            "dimmer": False,
        },
        {
            "app_id": "powerpnt.exe",
            "breaks": "yes",
            "focus": True,
            "filter": False,
            "dimmer": False,
        },
    ],
)
def test_application_rules_reject_paths_and_non_boolean_flags(rule):
    from opencareyes.config.settings import Settings

    settings = Settings(MemoryStore())
    with pytest.raises(ValueError):
        settings.app_rules = (rule,)


def test_motion_mode_rejects_unknown_value():
    from opencareyes.config.settings import Settings

    settings = Settings(MemoryStore())
    with pytest.raises(ValueError, match="Unknown motion mode"):
        settings.motion_mode = "fast"


def test_application_rules_limit_and_duplicate_validation():
    from opencareyes.config.settings import Settings

    settings = Settings(MemoryStore())
    rule = {
        "app_id": "same.exe",
        "breaks": True,
        "focus": False,
        "filter": False,
        "dimmer": False,
    }
    with pytest.raises(ValueError, match="unique"):
        settings.app_rules = (rule, rule)

    too_many = tuple({**rule, "app_id": f"app-{index}.exe"} for index in range(101))
    with pytest.raises(ValueError, match="100"):
        settings.app_rules = too_many


def test_upsert_and_remove_application_rule():
    from opencareyes.config.settings import Settings

    settings = Settings(MemoryStore())
    first = {
        "app_id": "POWERPNT.EXE",
        "breaks": True,
        "focus": False,
        "filter": False,
        "dimmer": False,
    }
    settings.upsert_app_rule(first)
    settings.upsert_app_rule({**first, "breaks": False, "focus": True})

    assert len(settings.app_rules) == 1
    assert settings.app_rules[0]["focus"] is True
    settings.remove_app_rule("PowerPnt.exe")
    assert settings.app_rules == ()
