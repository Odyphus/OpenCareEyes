'''Regression tests for safe startup pet selection and recovery.'''

from pathlib import Path
from types import SimpleNamespace

from opencareyes.__main__ import (
    _load_companion,
    _restore_startup_outfit,
)
from opencareyes.application.pet_pack_registry import PetPackRegistry
from opencareyes.config.settings import Settings
from opencareyes.controller import AppController


FIXTURE_ROOT = Path(__file__).parent / 'fixtures' / 'pets'


class MemoryStore:
    def __init__(self):
        self.values = {}

    def value(self, key, default=None, type=None):
        value = self.values.get(key, default)
        if type is not None and value is not None:
            return type(value)
        return value

    def setValue(self, key, value):
        self.values[key] = value

    def allKeys(self):
        return list(self.values)

    def sync(self):
        return None

    def status(self):
        return 0

    def clear(self):
        self.values.clear()


def registry(root=FIXTURE_ROOT):
    return PetPackRegistry(root, app_version='0.5.0')


def test_missing_selection_falls_back_and_preserves_recovery_id():
    settings = Settings(MemoryStore())
    settings.active_pet_id = 'missing_pet'

    companion, error, fallback_used = _load_companion(settings, registry())

    assert companion.state.pet_id == 'snow_ferret'
    assert error is not None
    assert fallback_used is True
    assert settings.active_pet_id == 'snow_ferret'
    assert settings.recovery_pet_id == 'missing_pet'


def test_repaired_pack_is_restored_and_recovery_marker_is_cleared():
    settings = Settings(MemoryStore())
    settings.active_pet_id = 'snow_ferret'
    settings.recovery_pet_id = 'tiny_bird'

    companion, error, fallback_used = _load_companion(settings, registry())

    assert companion.state.pet_id == 'tiny_bird'
    assert error is None
    assert fallback_used is False
    assert settings.active_pet_id == 'tiny_bird'
    assert settings.recovery_pet_id == ''


def test_explicit_non_default_selection_clears_stale_recovery_marker():
    settings = Settings(MemoryStore())
    settings.active_pet_id = 'tiny_bird'
    settings.recovery_pet_id = 'missing_pet'

    companion, error, fallback_used = _load_companion(settings, registry())

    assert companion.state.pet_id == 'tiny_bird'
    assert error is None
    assert fallback_used is False
    assert settings.recovery_pet_id == ''


def test_broken_default_pack_keeps_preferences_untouched(tmp_path):
    settings = Settings(MemoryStore())

    companion, error, fallback_used = _load_companion(
        settings,
        registry(tmp_path),
    )

    assert companion is None
    assert error is not None
    assert fallback_used is False
    assert settings.active_pet_id == 'snow_ferret'
    assert settings.recovery_pet_id == ''


class StartupCompanion:
    def __init__(self):
        self.state = SimpleNamespace(pet_id='snow_ferret', outfit_id='')
        self.outfit_calls = []

    def set_outfit(self, outfit_id):
        self.outfit_calls.append(outfit_id)


class RecordingController:
    def __init__(self):
        self.outfit_calls = []

    def set_pet_outfit(self, outfit_id):
        self.outfit_calls.append(outfit_id)
        return True


class RejectingOutfitRepository:
    def request_outfit_preload(self, _manifest, _outfit_id, _request_id):
        return False


def test_startup_outfit_is_only_restored_through_public_controller_command():
    settings = Settings(MemoryStore())
    settings.wardrobe_mode = 'outfit'
    settings.outfit_preferences = {'snow_ferret': 'snow_slope_skier'}
    companion = StartupCompanion()
    controller = RecordingController()

    assert _restore_startup_outfit(settings, companion, controller) is True

    assert companion.outfit_calls == []
    assert controller.outfit_calls == ['snow_slope_skier']


def test_missing_startup_outfit_keeps_preference_and_reports_controller_error(qapp):
    settings = Settings(MemoryStore())
    settings.wardrobe_mode = 'outfit'
    settings.outfit_preferences = {'snow_ferret': 'missing_outfit'}
    companion, _, _ = _load_companion(settings, registry())
    controller = AppController(
        settings,
        companion=companion,
        pet_asset_repository=RejectingOutfitRepository(),
    )

    assert _restore_startup_outfit(settings, companion, controller) is False

    assert companion.wardrobe_mode == 'automatic'
    assert companion.state.outfit_id == ''
    assert settings.wardrobe_mode == 'outfit'
    assert settings.outfit_preferences == {'snow_ferret': 'missing_outfit'}
    assert controller.state.pet_wardrobe.error == (
        '造型资源无法加载，已保留当前造型。'
    )
