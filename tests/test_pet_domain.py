'''Pure tests for immutable pet values and semantic priority.'''

from dataclasses import FrozenInstanceError

import pytest

from opencareyes.domain.pet import (
    PetAction,
    PetEvent,
    PetEventPriority,
    PetFrame,
    PetOutfitDefinition,
    PetPackManifest,
    PetPersonality,
    PetState,
    PetVisualTheme,
    normalise_resource_path,
)


def actions():
    frame = PetFrame('sprites/base.png', 100)
    names = (
        'idle', 'sleep', 'move', 'click_reaction', 'drag_hold',
        'drag_release', 'right_click_reaction', 'rest_prompt',
    )
    return {name: PetAction(name, (frame,), loop=name in {'idle', 'sleep', 'move'}) for name in names}


def manifest(**overrides):
    values = {
        'schema_version': 1,
        'pet_id': 'test_pet',
        'display_name': 'Test Pet',
        'pack_version': '1.0.0',
        'min_app_version': '0.5.0',
        'author': 'Tests',
        'license': 'Apache-2.0',
        'canvas_size': (100, 80),
        'default_scale': 100,
        'personality': PetPersonality(),
        'actions': actions(),
        'event_bindings': {},
    }
    values.update(overrides)
    return PetPackManifest(**values)


def outfit(**overrides):
    frame = PetFrame('outfits/skier/atlas.png', 100, (0, 0, 64, 64))
    values = {
        'outfit_id': 'snow_slope_skier',
        'display_name': '雪坡滑雪客',
        'description': '薄荷绿滑雪外套与浅蓝护目镜。',
        'thumbnail_path': 'outfits/skier/thumbnail.png',
        'preview_path': 'outfits/skier/preview.png',
        'actions': {
            'idle': PetAction('idle', (frame,), loop=True),
            'move': PetAction('move', (frame,), loop=True),
        },
        'ambient_layers': {'snow': 'outfits/skier/snow.png'},
    }
    values.update(overrides)
    return PetOutfitDefinition(**values)


def test_domain_values_are_immutable_and_mappings_are_deeply_frozen():
    pet = manifest(appearance_rules={'weather.snow': {'neckwear': 'scarf.png'}})

    with pytest.raises(FrozenInstanceError):
        pet.pet_id = 'other'
    with pytest.raises(TypeError):
        pet.actions['other'] = pet.actions['idle']
    with pytest.raises(TypeError):
        pet.appearance_rules['weather.snow']['neckwear'] = 'other.png'


@pytest.mark.parametrize(
    'path',
    ['', '../escape.png', 'sprites/../../escape.png', 'C:/pet.png', '/pet.png', 'a\\b.png'],
)
def test_resource_paths_cannot_leave_the_pack(path):
    with pytest.raises(ValueError):
        normalise_resource_path(path)


def test_manifest_requires_every_cross_species_baseline_action():
    incomplete = actions()
    del incomplete['drag_release']

    with pytest.raises(ValueError, match='drag_release'):
        manifest(actions=incomplete)


def test_unbound_optional_event_falls_back_to_idle_without_breaking_feature():
    pet = manifest()

    assert pet.action_for_event('weather.snow').action_id == 'idle'
    assert pet.action_for_event('click').action_id == 'click_reaction'


@pytest.mark.parametrize(
    ('kind', 'priority'),
    [
        ('autonomous.idle', PetEventPriority.AUTONOMOUS),
        ('application.word', PetEventPriority.APPLICATION),
        ('avoidance.window', PetEventPriority.AVOIDANCE),
        ('break.due', PetEventPriority.REMINDER),
        ('click', PetEventPriority.INTERACTION),
        ('break.active', PetEventPriority.REST),
        ('session.locked', PetEventPriority.SAFETY),
    ],
)
def test_event_priority_is_derived_from_semantics(kind, priority):
    assert PetEvent(kind).priority == priority


def test_callers_and_resource_packs_cannot_escalate_event_priority():
    with pytest.raises(ValueError, match='fixed'):
        PetEvent('click', priority=PetEventPriority.SAFETY)


def test_personality_is_bounded_and_cannot_change_business_rules():
    with pytest.raises(ValueError):
        PetPersonality(activity=101)

    assert PetPersonality(walk_speed=10).walk_speed == 10.0


def test_schema_v2_frames_and_visual_theme_are_validated():
    frame = PetFrame('sprites/atlas.png', 50, (0, 0, 64, 64))
    pet = manifest(
        schema_version=2,
        actions={
            name: PetAction(name, (frame,))
            for name in actions()
        },
        visual_theme=PetVisualTheme(accent='#6b9eea'),
        asset_scale=2,
    )

    assert pet.schema_version == 2
    assert frame.source_rect == (0, 0, 64, 64)
    assert pet.visual_theme.accent == '#6B9EEA'

    with pytest.raises(ValueError, match='source_rect'):
        PetFrame('sprites/atlas.png', 50, (0, 0, 0, 64))


def test_schema_v3_outfits_are_immutable_and_fall_back_only_to_their_idle():
    skier = outfit()
    pet = manifest(
        schema_version=3,
        outfits={skier.outfit_id: skier},
        event_bindings={'click': 'click_reaction'},
    )

    with pytest.raises(TypeError):
        pet.outfits['other'] = skier
    with pytest.raises(TypeError):
        skier.ambient_layers['snow'] = 'other.png'
    assert pet.action_for_event('autonomous.move', outfit_id=skier.outfit_id).action_id == 'move'
    assert pet.action_for_event('click', outfit_id=skier.outfit_id) is skier.actions['idle']
    assert pet.action_for_event('weather.snow', outfit_id=skier.outfit_id) is skier.actions['idle']


@pytest.mark.parametrize('outfit_id', ['', 'Snow_skier', '../skier', 'a' * 65])
def test_outfit_identifiers_are_safe(outfit_id):
    with pytest.raises(ValueError, match='outfit identifier'):
        outfit(outfit_id=outfit_id)


def test_outfit_requires_its_own_idle_and_limits_total_frames():
    with pytest.raises(ValueError, match='idle'):
        outfit(actions={'move': outfit().actions['move']})

    frame = PetFrame('outfits/skier/atlas.png', 100)
    with pytest.raises(ValueError, match='60'):
        outfit(actions={'idle': PetAction('idle', (frame,) * 61)})


def test_runtime_pet_state_accepts_only_a_safe_optional_outfit_id():
    assert PetState('test_pet', outfit_id='snow_slope_skier').outfit_id == (
        'snow_slope_skier'
    )
    with pytest.raises(ValueError, match='outfit identifier'):
        PetState('test_pet', outfit_id='Snow_skier')
