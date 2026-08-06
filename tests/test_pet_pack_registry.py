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
from opencareyes.constants import APP_VERSION, PETS_DIR
from opencareyes.domain.pet import REQUIRED_ACTIONS

FIXTURE_ROOT = Path(__file__).parent / 'fixtures' / 'pets'


def test_official_snow_ferret_pack_is_complete_and_buildable():
    registry = PetPackRegistry(PETS_DIR, app_version=APP_VERSION)

    manifest = registry.load('snow_ferret')

    assert REQUIRED_ACTIONS.issubset(manifest.actions)
    assert manifest.event_bindings['click'] == 'click_reaction'
    assert manifest.appearance_rules == {}
    assert manifest.schema_version == 3
    assert 'snow_slope_skier' in manifest.outfits
    assert {'round_shades', 'star_shades'} <= set(manifest.outfits)
    assert len(manifest.outfits['snow_slope_skier'].actions) == 10
    assert manifest.asset_scale == 2
    assert manifest.visual_theme.accent == '#6B9EEA'

    legacy_accessories = Path(PETS_DIR) / 'snow_ferret' / 'accessories'
    assert not legacy_accessories.exists()
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


def outfit_json(
    *,
    outfit_id='snow_slope_skier',
    actions=None,
    thumbnail_path='preview.png',
    preview_path='preview.png',
    ambient_layers=None,
):
    if actions is None:
        actions = {
            'idle': {
                'loop': True,
                'frames': [
                    {
                        'path': 'sprites/base.png',
                        'duration_ms': 100,
                        'source_rect': [0, 0, 16, 16],
                    }
                ],
            },
            'move': {
                'loop': True,
                'frames': [{'path': 'sprites/base.png', 'duration_ms': 100}],
            },
        }
    return {
        outfit_id: {
            'display_name': '雪坡滑雪客',
            'description': '薄荷绿滑雪外套与浅蓝护目镜。',
            'thumbnail_path': thumbnail_path,
            'preview_path': preview_path,
            'actions': actions,
            'ambient_layers': ambient_layers or {'snow': 'preview.png'},
        }
    }


def make_schema_v3(pack, **outfit_options):
    def change(data):
        data['schema_version'] = 3
        data['outfits'] = outfit_json(**outfit_options)

    update_manifest(pack, change)


def test_discovers_two_different_species_without_core_hard_coding():
    registry = PetPackRegistry(FIXTURE_ROOT, app_version='0.5.0')

    manifests = registry.discover()

    assert [item.pet_id for item in manifests] == ['snow_ferret', 'tiny_bird']
    assert manifests[0].canvas_size == (160, 160)
    assert manifests[1].canvas_size == (96, 72)
    assert registry.resolve_action('snow_ferret', 'click').action_id == 'paw_cursor'
    assert registry.resolve_action('tiny_bird', 'click').action_id == 'peck'
    bird_outfit = manifests[1].outfits['rain_cape']
    assert bird_outfit.display_name == '雨披小团雀'
    assert registry.resolve_action(
        'tiny_bird', 'click', outfit_id=bird_outfit.outfit_id
    ) is bird_outfit.actions['idle']
    assert registry.errors == {}


def test_loads_schema_v3_outfit_and_resolves_missing_action_to_outfit_idle(tmp_path):
    root, pack = copy_pet(tmp_path)
    make_schema_v3(pack)

    registry = PetPackRegistry(root, app_version='0.8.0')
    manifest = registry.load('snow_ferret')
    outfit = manifest.outfits['snow_slope_skier']

    assert manifest.schema_version == 3
    assert outfit.display_name == '雪坡滑雪客'
    assert registry.resolve_action(
        'snow_ferret', 'autonomous.move', outfit_id=outfit.outfit_id
    ).action_id == 'move'
    assert registry.resolve_action(
        'snow_ferret', 'click', outfit_id=outfit.outfit_id
    ) is outfit.actions['idle']


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


@pytest.mark.parametrize(
    ('field', 'unsafe_path'),
    [
        ('thumbnail_path', '../thumbnail.png'),
        ('preview_path', 'C:/preview.png'),
        ('ambient_layers', '../snow.png'),
        ('frame', 'https://bad/atlas.png'),
    ],
)
def test_rejects_unsafe_outfit_resource_paths(tmp_path, field, unsafe_path):
    root, pack = copy_pet(tmp_path)
    options = {}
    if field == 'ambient_layers':
        options[field] = {'snow': unsafe_path}
    elif field == 'frame':
        options['actions'] = {
            'idle': {'frames': [{'path': unsafe_path, 'duration_ms': 100}]}
        }
    else:
        options[field] = unsafe_path
    make_schema_v3(pack, **options)

    with pytest.raises(PetPackValidationError):
        PetPackRegistry(root, app_version='0.8.0').load('snow_ferret')


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


@pytest.mark.parametrize('outfit_id', ['Snow_skier', '../skier', 'x' * 65])
def test_rejects_invalid_outfit_id(tmp_path, outfit_id):
    root, pack = copy_pet(tmp_path)
    make_schema_v3(pack, outfit_id=outfit_id)

    with pytest.raises(PetPackValidationError, match='outfit identifier'):
        PetPackRegistry(root, app_version='0.8.0').load('snow_ferret')


def test_rejects_outfit_without_idle_action(tmp_path):
    root, pack = copy_pet(tmp_path)
    make_schema_v3(
        pack,
        actions={
            'move': {'frames': [{'path': 'sprites/base.png', 'duration_ms': 100}]}
        },
    )

    with pytest.raises(PetPackValidationError, match='idle'):
        PetPackRegistry(root, app_version='0.8.0').load('snow_ferret')


def test_rejects_more_than_60_frames_in_one_outfit(tmp_path):
    root, pack = copy_pet(tmp_path)
    frame = {'path': 'sprites/base.png', 'duration_ms': 100}
    make_schema_v3(pack, actions={'idle': {'frames': [frame] * 61}})

    with pytest.raises(PetPackValidationError, match='60'):
        PetPackRegistry(root, app_version='0.8.0').load('snow_ferret')


def test_rejects_more_than_512_outfit_frame_descriptions(tmp_path):
    root, pack = copy_pet(tmp_path)

    def change(data):
        data['schema_version'] = 3
        frame = {'path': 'sprites/base.png', 'duration_ms': 100}
        data['outfits'] = {}
        for index in range(9):
            data['outfits'].update(
                outfit_json(
                    outfit_id=f'outfit_{index}',
                    actions={'idle': {'frames': [frame] * 60}},
                )
            )

    update_manifest(pack, change)

    with pytest.raises(PetPackValidationError, match='512'):
        PetPackRegistry(root, app_version='0.8.0').load('snow_ferret')


def test_rejects_outfit_source_rect_outside_atlas(tmp_path):
    root, pack = copy_pet(tmp_path)
    make_schema_v3(
        pack,
        actions={
            'idle': {
                'frames': [
                    {
                        'path': 'sprites/base.png',
                        'duration_ms': 100,
                        'source_rect': [5_000, 5_000, 80, 80],
                    }
                ]
            }
        },
    )

    with pytest.raises(PetPackValidationError, match='source_rect leaves its atlas'):
        PetPackRegistry(root, app_version='0.8.0').load('snow_ferret')


def test_prerelease_application_version_can_validate_matching_pack(tmp_path):
    root, pack = copy_pet(tmp_path)
    update_manifest(pack, lambda data: data.update(min_app_version='0.8.0b1'))

    manifest = PetPackRegistry(root, app_version='0.8.0b1').load('snow_ferret')

    assert manifest.min_app_version == '0.8.0b1'


def test_prerelease_application_does_not_satisfy_stable_minimum(tmp_path):
    root, pack = copy_pet(tmp_path)
    update_manifest(pack, lambda data: data.update(min_app_version='0.8.0'))

    with pytest.raises(PetPackValidationError, match='requires OpenCareEyes'):
        PetPackRegistry(root, app_version='0.8.0b1').load('snow_ferret')


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
