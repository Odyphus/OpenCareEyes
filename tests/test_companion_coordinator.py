'''Tests for deterministic desktop companion behaviour arbitration.'''

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from opencareyes.application.companion_coordinator import CompanionCoordinator
from opencareyes.application.pet_pack_registry import PetPackNotFoundError, PetPackRegistry
from opencareyes.constants import PETS_DIR
from opencareyes.domain.pet import PetEventPriority

FIXTURE_ROOT = Path(__file__).parent / 'fixtures' / 'pets'


class FakeClock:
    def __init__(self, value=10.0):
        self.value = value

    def __call__(self):
        return self.value


class FakeRandom:
    def __init__(self, value):
        self.value = value

    def random(self):
        return self.value


def coordinator(*, pet_id='snow_ferret', clock=None, random_source=None):
    registry = PetPackRegistry(FIXTURE_ROOT, app_version='0.5.0')
    return CompanionCoordinator(
        registry,
        pet_id,
        clock=clock or FakeClock(),
        random_source=random_source,
    )


def test_dispatch_uses_pack_binding_and_injected_monotonic_clock():
    clock = FakeClock(42.5)
    pet = coordinator(clock=clock)

    assert pet.dispatch_kind('click') is True

    assert pet.state.behavior.action_id == 'paw_cursor'
    assert pet.state.behavior.started_at == 42.5
    assert pet.state.behavior.priority == PetEventPriority.INTERACTION


def test_fixed_priority_prevents_lower_event_from_interrupting_safety_or_rest():
    pet = coordinator()

    assert pet.dispatch_kind('break.active') is True
    assert pet.dispatch_kind('click') is False
    assert pet.state.behavior.priority == PetEventPriority.REST
    assert pet.dispatch_kind('session.locked') is True
    assert pet.dispatch_kind('break.active') is False
    assert pet.state.behavior.event_kind == 'session.locked'


def test_same_semantic_tick_does_not_restart_current_animation():
    clock = FakeClock(10)
    pet = coordinator(clock=clock)
    pet.dispatch_kind('break.due')
    started_at = pet.state.behavior.started_at
    clock.value = 11

    assert pet.dispatch_kind('break.due') is False
    assert pet.state.behavior.started_at == started_at


def test_cursor_tracking_does_not_interrupt_autonomous_walk():
    pet = coordinator()

    assert pet.dispatch_kind('autonomous.move') is True
    assert pet.state.behavior.action_id == 'move'

    assert pet.dispatch_kind('cursor.near') is False
    assert pet.state.behavior.action_id == 'move'
    assert pet.state.behavior.event_kind == 'autonomous.move'


def test_clear_event_releases_priority_and_stale_completion_is_ignored():
    pet = coordinator()
    pet.dispatch_kind('session.locked')

    assert pet.complete_action('different') is False
    assert pet.clear_event('other') is False
    assert pet.clear_event('session.locked') is True
    assert pet.state.behavior.action_id == 'idle'
    assert pet.dispatch_kind('click') is True


def test_missing_optional_action_uses_idle_without_blocking_semantic_event():
    pet = coordinator(pet_id='tiny_bird')

    assert pet.dispatch_kind('weather.snow') is True
    assert pet.state.behavior.action_id == 'idle'
    assert pet.state.behavior.event_kind == 'weather.snow'


def test_switching_pet_preloads_before_change_and_preserves_runtime_visibility():
    pet = coordinator()
    pet.set_visible(False)
    pet.set_bubble_visible(True)

    switched = pet.set_active_pet('tiny_bird')

    assert switched.pet_id == 'tiny_bird'
    assert switched.visible is False
    assert switched.bubble_visible is True
    with pytest.raises(PetPackNotFoundError):
        pet.set_active_pet('missing_pet')
    assert pet.state.pet_id == 'tiny_bird'


def test_autonomous_choice_uses_injected_random_source_and_personality():
    pet = coordinator(random_source=FakeRandom(0.70))

    chosen = pet.choose_autonomous_action()

    assert chosen.action_id == 'play'
    assert pet.start_autonomous_action() is True
    assert pet.state.behavior.action_id == 'play'


def test_appearance_uses_semantic_slots_and_state_is_immutable():
    pet = coordinator()

    state = pet.set_appearance('held_item', 'pine_cone')

    assert state.appearance.held_item == 'pine_cone'
    with pytest.raises(ValueError):
        pet.set_appearance('tail', 'ribbon')
    with pytest.raises(FrozenInstanceError):
        state.visible = False


def test_interactive_and_manual_appearance_override_automatic_conditions():
    pet = coordinator()

    automatic = pet.apply_appearance_conditions(('weather.snow',))
    assert automatic.appearance.neckwear == 'accessories/scarf.png'

    manual = pet.set_manual_accessory('neckwear', 'scarf')
    assert manual.appearance.neckwear == 'accessories/scarf.png'

    interactive = pet.apply_appearance_conditions(
        ('weather.snow',),
        interactive={'neckwear': 'item_scarf.png'},
    )
    assert interactive.appearance.neckwear == 'item_scarf.png'
    assert pet.clear_interactive_appearance().appearance.neckwear == 'accessories/scarf.png'


def test_official_interaction_item_is_transient_and_clears_after_action():
    pet = CompanionCoordinator(
        PetPackRegistry(PETS_DIR, app_version='0.6.0'),
        'snow_ferret',
    )

    assert pet.offer_item('hot_cocoa') is True
    assert pet.state.behavior.action_id == 'play'
    assert pet.state.appearance.held_item == 'accessories/hot_cocoa.png'
    assert pet.complete_action('play') is True
    assert pet.state.behavior.action_id == 'idle'
    assert pet.state.appearance.held_item == ''
