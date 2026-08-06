'''Pure orchestration for pet selection and semantic behaviour arbitration.'''

from __future__ import annotations

import random
import time
from collections.abc import Callable, Mapping
from dataclasses import replace
from typing import Any

from opencareyes.application.pet_pack_registry import PetPackRegistry
from opencareyes.domain.pet import (
    APPEARANCE_SLOTS,
    PetAction,
    PetAppearance,
    PetBehavior,
    PetEvent,
    PetPackManifest,
    PetState,
)


class CompanionCoordinator:
    '''Single state-machine boundary for one active desktop companion.'''

    def __init__(
        self,
        registry: PetPackRegistry,
        active_pet_id: str | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
        random_source: random.Random | None = None,
    ):
        self._registry = registry
        self._clock = clock
        self._random = random_source or random.Random()
        self._wardrobe_mode = 'automatic'
        self._selected_outfit_id = ''
        if active_pet_id is None:
            catalog = registry.available_pets()
            if not catalog:
                raise ValueError('No valid pet packs are available')
            active_pet_id = catalog[0].pet_id
        self._manifest = registry.load(active_pet_id)
        self._state = PetState(
            pet_id=self._manifest.pet_id,
            behavior=self._idle_behavior(),
        )

    @property
    def state(self) -> PetState:
        return self._state

    @property
    def registry(self) -> PetPackRegistry:
        return self._registry

    @property
    def manifest(self) -> PetPackManifest:
        return self._manifest

    @property
    def current_action(self) -> PetAction:
        actions = self._effective_actions()
        return actions.get(
            self._state.behavior.action_id,
            actions['idle'],
        )

    @property
    def wardrobe_mode(self) -> str:
        return self._wardrobe_mode

    @property
    def selected_outfit_id(self) -> str:
        return self._selected_outfit_id

    def set_active_pet(self, pet_id: str) -> PetState:
        '''Validate and preload before replacing the current pet.'''

        candidate = self._registry.load(pet_id)
        if candidate.pet_id == self._manifest.pet_id:
            return self._state
        previous = self._state
        self._manifest = candidate
        self._wardrobe_mode = 'automatic'
        self._selected_outfit_id = ''
        self._state = PetState(
            pet_id=candidate.pet_id,
            behavior=self._idle_behavior(),
            appearance=PetAppearance(),
            enabled=previous.enabled,
            visible=previous.visible,
            bubble_visible=previous.bubble_visible,
            suppressed_by=previous.suppressed_by,
        )
        return self._state

    def set_outfit(self, outfit_id: str | None) -> PetState:
        '''Select one validated full replacement outfit or restore automation.'''

        selected = '' if outfit_id in {None, ''} else str(outfit_id).strip().lower()
        if selected and selected not in getattr(self._manifest, 'outfits', {}):
            raise ValueError(f'Unknown pet outfit: {selected!r}')
        self._wardrobe_mode = 'outfit' if selected else 'automatic'
        self._selected_outfit_id = selected
        self._state = replace(
            self._state,
            outfit_id=selected,
            behavior=self._idle_behavior(),
            appearance=PetAppearance(),
        )
        return self._state

    def set_wardrobe_mode(
        self,
        mode: str,
        outfit_id: str | None = None,
    ) -> PetState:
        normalized = str(mode).strip().lower()
        if normalized == 'outfit':
            return self.set_outfit(outfit_id)
        if normalized != 'automatic':
            raise ValueError(f'Unknown wardrobe mode: {mode!r}')
        self._wardrobe_mode = normalized
        self._selected_outfit_id = ''
        self._state = replace(
            self._state,
            outfit_id='',
            behavior=self._idle_behavior(),
            appearance=PetAppearance(),
        )
        return self._state

    def select_pet(self, pet_id: str) -> PetState:
        '''Compatibility command used by the application controller.'''

        return self.set_active_pet(pet_id)

    def dispatch_kind(
        self,
        kind: str,
        payload: Mapping[str, Any] | None = None,
    ) -> bool:
        return self.dispatch(
            PetEvent(kind=kind, payload=payload or {}, occurred_at=self._clock())
        )

    def dispatch(self, event: PetEvent) -> bool:
        '''Apply one event if fixed priority arbitration permits it.'''

        if not isinstance(event, PetEvent):
            raise TypeError('dispatch requires a PetEvent')
        action = self._action_for_event(event.kind)
        current = self._state.behavior
        if (
            current.event_kind == 'autonomous.move'
            and event.kind.startswith('cursor.')
        ):
            return False
        if event.priority < current.priority:
            return False
        if current.event_kind == event.kind and current.action_id == action.action_id:
            return False
        self._state = replace(
            self._state,
            behavior=PetBehavior(
                action_id=action.action_id,
                event_kind=event.kind,
                priority=event.priority,
                started_at=event.occurred_at,
            ),
        )
        return True

    def complete_action(self, action_id: str | None = None) -> bool:
        '''Return to idle after the animator finishes the current one-shot.'''

        if action_id is not None and action_id != self._state.behavior.action_id:
            return False
        if self._state.behavior.event_kind == 'autonomous.idle':
            return False
        self._state = replace(self._state, behavior=self._idle_behavior())
        return True

    def clear_event(self, event_kind: str | None = None) -> bool:
        if event_kind is not None and event_kind != self._state.behavior.event_kind:
            return False
        return self.complete_action()

    def sync_break_behavior(self, phase: str, prompt_stage: str = 'none') -> bool:
        '''Keep the companion action aligned with the break state machine.'''

        if str(phase) == 'resting':
            return self.dispatch_kind('rest.sleep')

        changed = False
        if self._state.behavior.event_kind in {'break.due', 'rest.sleep'}:
            changed = self.complete_action()
        if str(prompt_stage) not in {'none', 'hidden'}:
            changed = self.dispatch_kind('break.due') or changed
        return changed

    def choose_autonomous_action(self) -> PetAction:
        '''Choose a presentation action using injected, testable randomness.'''

        personality = self._manifest.personality
        actions = self._effective_actions()
        weighted: list[tuple[str, float]] = [('idle', 100.0)]
        if 'move' in actions:
            weighted.append(('move', float(personality.activity)))
        if 'play' in actions:
            weighted.append(('play', float(personality.playfulness)))
        if 'sleep' in actions:
            weighted.append(('sleep', float(personality.sleepiness)))
        weighted = [(name, weight) for name, weight in weighted if weight > 0]
        total = sum(weight for _name, weight in weighted)
        cursor = self._random.random() * total
        selected = weighted[-1][0]
        for action_id, weight in weighted:
            cursor -= weight
            if cursor <= 0:
                selected = action_id
                break
        return actions[selected]

    def start_autonomous_action(self) -> bool:
        action = self.choose_autonomous_action()
        event_kind = f'autonomous.{action.action_id}'
        return self.dispatch_kind(event_kind)

    def set_appearance(self, slot: str, item_id: str | None) -> PetState:
        if slot not in APPEARANCE_SLOTS:
            raise ValueError(f'Unsupported appearance slot: {slot}')
        value = '' if item_id is None else str(item_id).strip()
        self._state = replace(
            self._state,
            appearance=replace(self._state.appearance, **{slot: value}),
        )
        return self._state

    def set_enabled(self, enabled: bool) -> PetState:
        self._state = replace(self._state, enabled=bool(enabled))
        return self._state

    def set_visible(self, visible: bool) -> PetState:
        self._state = replace(self._state, visible=bool(visible))
        return self._state

    def set_bubble_visible(self, visible: bool) -> PetState:
        self._state = replace(self._state, bubble_visible=bool(visible))
        return self._state

    def set_suppressed_by(self, reasons: tuple[str, ...]) -> PetState:
        normalised = tuple(dict.fromkeys(str(reason) for reason in reasons if reason))
        self._state = replace(self._state, suppressed_by=normalised)
        return self._state

    def _idle_behavior(self) -> PetBehavior:
        return PetBehavior(started_at=float(self._clock()))

    def _effective_actions(self) -> Mapping[str, PetAction]:
        outfit_id = str(getattr(self._state, 'outfit_id', ''))
        outfit = getattr(self._manifest, 'outfits', {}).get(outfit_id)
        actions = getattr(outfit, 'actions', None)
        return actions if isinstance(actions, Mapping) and 'idle' in actions else self._manifest.actions

    def _action_for_event(self, event_kind: str) -> PetAction:
        base_action = self._manifest.action_for_event(event_kind)
        actions = self._effective_actions()
        return actions.get(base_action.action_id, actions['idle'])
