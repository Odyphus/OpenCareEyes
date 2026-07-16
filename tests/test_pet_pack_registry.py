'''Security and compatibility tests for declaration-only pet packs.'''

import json
import shutil
from pathlib import Path

import pytest
from PySide6.QtGui import QImage

import opencareyes.application.pet_pack_registry as registry_module
from opencareyes.application.pet_pack_registry import (
    PetPackNotFoundError,
    PetPackRegistry,
    PetPackValidationError,
)
from opencareyes.constants import PETS_DIR
from opencareyes.domain.pet import REQUIRED_ACTIONS

FIXTURE_ROOT = Path(__file__).parent / 'fixtures' / 'pets'


def test_official_snow_ferret_pack_is_complete_and_buildable():
    registry = PetPackRegistry(PETS_DIR, app_version='0.6.0')

    manifest = registry.load('snow_ferret')

    assert REQUIRED_ACTIONS.issubset(manifest.actions)
    assert manifest.event_bindings['click'] == 'click_reaction'
    assert manifest.appearance_rules['weather.snow']['neckwear']
    assert manifest.appearance_rules['holiday.christmas']['scene']
    assert manifest.schema_version == 2
    assert manifest.asset_scale == 2
    assert manifest.visual_theme.accent == '#6B9EEA'
    assert any(
        frame.source_rect is not None
        for action in manifest.actions.values()
        for frame in action.frames
    )
    for action in manifest.actions.values():
        for frame in action.frames:
            assert registry.resolve_resource('snow_ferret', frame.path).is_file()


def copy_pet(tmp_path, pet_id='snow_ferret'):
    root = tmp_path / 'pets'
    root.mkdir(exist_ok=True)
    shutil.copytree(FIXTURE_ROOT / pet_id, root / pet_id)
    return root, root / pet_id


def update_manifest(pack_dir, change):
    path = pack_dir / 'manifest.json'
    data = json.loads(path.read_text(encoding='utf-8'))
    change(data)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')


def test_discovers_two_different_species_without_core_hard_coding():
    registry = PetPackRegistry(FIXTURE_ROOT, app_version='0.5.0')

    manifests = registry.discover()

    assert [item.pet_id for item in manifests] == ['snow_ferret', 'tiny_bird']
    assert manifests[0].canvas_size == (160, 160)
    assert manifests[1].canvas_size == (96, 72)
    assert registry.resolve_action('snow_ferret', 'click').action_id == 'paw_cursor'
    assert registry.resolve_action('tiny_bird', 'click').action_id == 'peck'
    assert registry.errors == {}


def test_resolve_resource_returns_only_a_validated_file_inside_pack():
    registry = PetPackRegistry(FIXTURE_ROOT, app_version='0.5.0')

    path = registry.resolve_resource('snow_ferret', 'sprites/base.png')

    assert path.name == 'base.png'
    assert path.is_file()
    with pytest.raises((ValueError, PetPackValidationError)):
        registry.resolve_resource('snow_ferret', '../outside.png')


@pytest.mark.parametrize(
    'unsafe_path',
    ['../outside.png', 'sprites/../../outside.png', 'C:/outside.png', 'https://bad/pet.png'],
)
def test_rejects_path_traversal_drive_paths_and_urls(tmp_path, unsafe_path):
    root, pack = copy_pet(tmp_path)

    def change(data):
        data['actions']['idle']['frames'][0]['path'] = unsafe_path

    update_manifest(pack, change)

    with pytest.raises(PetPackValidationError):
        PetPackRegistry(root, app_version='0.5.0').load('snow_ferret')


def test_rejects_executable_or_unknown_resource_extensions(tmp_path):
    root, pack = copy_pet(tmp_path)
    (pack / 'payload.py').write_text('raise SystemExit', encoding='utf-8')

    with pytest.raises(PetPackValidationError, match='extension'):
        PetPackRegistry(root, app_version='0.5.0').load('snow_ferret')


def test_rejects_resource_over_size_limit(tmp_path, monkeypatch):
    root, pack = copy_pet(tmp_path)
    monkeypatch.setattr(registry_module, 'MAX_RESOURCE_BYTES', 4)

    with pytest.raises(PetPackValidationError, match='too large'):
        PetPackRegistry(root, app_version='0.5.0').load('snow_ferret')


def test_rejects_renamed_non_png_resource(tmp_path):
    root, pack = copy_pet(tmp_path)
    (pack / 'sprites' / 'invalid.png').write_text('not a png', encoding='utf-8')

    with pytest.raises(PetPackValidationError, match='PNG is invalid'):
        PetPackRegistry(root, app_version='0.5.0').load('snow_ferret')


def test_rejects_png_with_excessive_decoded_dimensions(tmp_path):
    root, pack = copy_pet(tmp_path)
    oversized = QImage(5_000, 1, QImage.Format_ARGB32)
    oversized.fill(0)
    assert oversized.save(str(pack / 'sprites' / 'oversized.png'))

    with pytest.raises(PetPackValidationError, match='dimensions are too large'):
        PetPackRegistry(root, app_version='0.5.0').load('snow_ferret')


def test_rejects_missing_required_action_and_broken_binding(tmp_path):
    root, pack = copy_pet(tmp_path)

    def change(data):
        del data['actions']['drag_hold']
        data['event_bindings']['click'] = 'missing_action'

    update_manifest(pack, change)

    with pytest.raises(PetPackValidationError, match='required actions'):
        PetPackRegistry(root, app_version='0.5.0').load('snow_ferret')


def test_rejects_future_version_without_publishing_pack(tmp_path):
    root, pack = copy_pet(tmp_path)
    update_manifest(pack, lambda data: data.update(min_app_version='9.0.0'))

    registry = PetPackRegistry(root, app_version='0.5.0')

    assert registry.discover() == ()
    assert 'requires OpenCareEyes' in registry.errors['snow_ferret']


def test_invalid_sibling_is_isolated_from_valid_catalog(tmp_path):
    root, _pack = copy_pet(tmp_path)
    shutil.copytree(FIXTURE_ROOT / 'tiny_bird', root / 'tiny_bird')
    shutil.copytree(FIXTURE_ROOT / 'tiny_bird', root / 'broken_pet')
    update_manifest(root / 'broken_pet', lambda data: data.update(pet_id='wrong_id'))

    registry = PetPackRegistry(root, app_version='0.5.0')

    assert [item.pet_id for item in registry.discover()] == ['snow_ferret', 'tiny_bird']
    assert 'broken_pet' in registry.errors


def test_load_rejects_invalid_identifier_before_touching_filesystem():
    registry = PetPackRegistry(FIXTURE_ROOT, app_version='0.5.0')

    with pytest.raises(PetPackNotFoundError):
        registry.load('../snow_ferret')
