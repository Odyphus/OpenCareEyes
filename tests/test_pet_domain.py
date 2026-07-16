'''Pure tests for immutable pet values and semantic priority.'''

from dataclasses import FrozenInstanceError

import pytest

from opencareyes.domain.pet import (
    PetAction,
    PetEvent,
    PetEventPriority,
    PetFrame,
    PetPackManifest,
    PetPersonality,
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
