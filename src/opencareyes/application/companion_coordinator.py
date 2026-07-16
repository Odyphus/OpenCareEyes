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
        self._manual_appearance: dict[str, str] = {}
        self._interactive_appearance: dict[str, str] = {}
        self._appearance_conditions: tuple[str, ...] = ()
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
        return self._manifest.actions.get(
            self._state.behavior.action_id,
            self._manifest.actions['idle'],
        )

    def set_active_pet(self, pet_id: str) -> PetState:
        '''Validate and preload before replacing the current pet.'''

        candidate = self._registry.load(pet_id)
        if candidate.pet_id == self._manifest.pet_id:
            return self._state
        previous = self._state
        self._manifest = candidate
        self._manual_appearance.clear()
        self._interactive_appearance.clear()
        self._appearance_conditions = ()
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

    def select_pet(self, pet_id: str) -> PetState:
        '''Compatibility command used by the application controller.'''

        return self.set_active_pet(pet_id)

    def set_manual_accessory(self, slot: str, item_id: str | None) -> PetState:
        if slot not in APPEARANCE_SLOTS:
            raise ValueError(f'Unsupported appearance slot: {slot}')
        if item_id in {None, ''}:
            self._manual_appearance.pop(slot, None)
        else:
            item = str(item_id).strip().lower()
            rule = self._manifest.appearance_rules.get(
                f'accessory.{item}',
                {},
            )
            resource = rule.get(slot) if isinstance(rule, Mapping) else None
            if not resource:
                raise ValueError(
                    f'Accessory {item!r} is not declared for slot {slot!r}'
                )
            self._manual_appearance[slot] = str(resource)
        return self.apply_appearance_conditions(self._appearance_conditions)

    def offer_item(self, item_id: str) -> bool:
        item = str(item_id).strip().lower()
        changed = self.dispatch_kind('item.offered', {'item_id': item})
        if not changed:
            return False
        rule = self._manifest.appearance_rules.get(f'item.{item}', {})
        if isinstance(rule, Mapping):
            self.apply_appearance_conditions(
                self._appearance_conditions,
                interactive=rule,
            )
        return True

    def apply_appearance_conditions(
        self,
        conditions: tuple[str, ...],
        *,
        interactive: Mapping[str, str] | None = None,
    ) -> PetState:
        '''Resolve semantic layers without making assumptions about anatomy.'''

        self._appearance_conditions = tuple(str(value) for value in conditions)
        resolved: dict[str, str] = {}
        for condition in self._appearance_conditions:
            rule = self._manifest.appearance_rules.get(str(condition), {})
            if not isinstance(rule, Mapping):
                continue
            for slot, resource in rule.items():
                if slot in APPEARANCE_SLOTS and resource:
                    resolved[str(slot)] = str(resource)
        resolved.update(self._manual_appearance)
        if interactive is not None:
            self._interactive_appearance = {
                str(slot): str(resource)
                for slot, resource in interactive.items()
                if slot in APPEARANCE_SLOTS and resource
            }
        resolved.update(self._interactive_appearance)
        self._state = replace(
            self._state,
            appearance=PetAppearance(
                **{slot: resolved.get(slot, '') for slot in APPEARANCE_SLOTS}
            ),
        )
        return self._state

    def clear_interactive_appearance(self) -> PetState:
        self._interactive_appearance.clear()
        return self.apply_appearance_conditions(self._appearance_conditions)

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
        action = self._manifest.action_for_event(event.kind)
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
        if self._state.behavior.event_kind == 'item.offered':
            self._interactive_appearance.clear()
            self.apply_appearance_conditions(self._appearance_conditions)
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

        changed = self.clear_event('rest.sleep')
        if str(prompt_stage) not in {'none', 'hidden'}:
            changed = self.dispatch_kind('break.due') or changed
        return changed

    def choose_autonomous_action(self) -> PetAction:
        '''Choose a presentation action using injected, testable randomness.'''

        personality = self._manifest.personality
        weighted: list[tuple[str, float]] = [('idle', 100.0)]
        weighted.append(('move', float(personality.activity)))
        if 'play' in self._manifest.actions:
            weighted.append(('play', float(personality.playfulness)))
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
        return self._manifest.actions[selected]

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
