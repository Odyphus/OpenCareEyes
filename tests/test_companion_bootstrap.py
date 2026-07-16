'''Regression tests for safe startup pet selection and recovery.'''

from pathlib import Path

from opencareyes.__main__ import _load_companion
from opencareyes.application.pet_pack_registry import PetPackRegistry
from opencareyes.config.settings import Settings


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
