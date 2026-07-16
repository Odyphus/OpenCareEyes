'''Immutable values for the declaration-only desktop pet engine.'''

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import Any

PET_PACK_SCHEMA_VERSION = 2
SUPPORTED_PET_PACK_SCHEMAS = frozenset({1, 2})
PET_ID_PATTERN = re.compile(r'^[a-z0-9_]{1,64}$')
ACTION_ID_PATTERN = re.compile(r'^[a-z0-9_.-]{1,64}$')
EVENT_KIND_PATTERN = re.compile(r'^[a-z0-9_.-]{1,96}$')
REQUIRED_ACTIONS = frozenset(
    {
        'idle', 'sleep', 'move', 'click_reaction', 'drag_hold',
        'drag_release', 'right_click_reaction', 'rest_prompt',
    }
)
APPEARANCE_SLOTS = (
    'headwear', 'neckwear', 'bodywear', 'held_item', 'scene', 'effect',
)


class PetEventPriority(IntEnum):
    '''Stable arbitration levels; resource packs cannot redefine these.'''

    AUTONOMOUS = 100
    APPLICATION = 200
    AVOIDANCE = 300
    REMINDER = 400
    INTERACTION = 500
    REST = 600
    SAFETY = 700


def priority_for_event_kind(kind: str) -> PetEventPriority:
    '''Return the fixed priority for a semantic event kind.'''

    normalised = _normalise_event_kind(kind)
    if normalised.startswith(('safety.', 'session.')) or normalised in {
        'context.fullscreen', 'context.suppressed',
    }:
        return PetEventPriority.SAFETY
    if normalised.startswith('rest.') or normalised in {'break.active', 'break.strict'}:
        return PetEventPriority.REST
    if normalised.startswith(('drag.', 'item.', 'tool.')) or normalised in {
        'click', 'right_click',
    }:
        return PetEventPriority.INTERACTION
    if normalised.startswith(('reminder.', 'hourly.')) or normalised == 'break.due':
        return PetEventPriority.REMINDER
    if normalised.startswith('avoidance.'):
        return PetEventPriority.AVOIDANCE
    if normalised.startswith(('application.', 'app.')):
        return PetEventPriority.APPLICATION
    return PetEventPriority.AUTONOMOUS


def normalise_resource_path(value: str) -> str:
    '''Validate one package-relative, POSIX-style resource path.'''

    path = str(value).strip()
    if not path or '\\' in path or '\0' in path or ':' in path:
        raise ValueError('Resource path must be a relative POSIX path')
    candidate = PurePosixPath(path)
    if candidate.is_absolute() or any(part in {'', '.', '..'} for part in candidate.parts):
        raise ValueError('Resource path cannot leave the pet pack')
    return candidate.as_posix()


def _normalise_action_id(value: str) -> str:
    action_id = str(value).strip().casefold()
    if not ACTION_ID_PATTERN.fullmatch(action_id):
        raise ValueError(f'Invalid pet action identifier: {value!r}')
    return action_id


def _normalise_event_kind(value: str) -> str:
    kind = str(value).strip().casefold()
    if not EVENT_KIND_PATTERN.fullmatch(kind):
        raise ValueError(f'Invalid pet event kind: {value!r}')
    return kind


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, set):
        return frozenset(_freeze(item) for item in value)
    return value


@dataclass(frozen=True, slots=True)
class PetPersonality:
    '''Presentation-only parameters for autonomous behaviour.'''

    activity: int = 50
    curiosity: int = 50
    playfulness: int = 50
    sleepiness: int = 50
    sociability: int = 50
    walk_speed: float = 32.0

    def __post_init__(self) -> None:
        names = ('activity', 'curiosity', 'playfulness', 'sleepiness', 'sociability')
        for name in names:
            value = int(getattr(self, name))
            if not 0 <= value <= 100:
                raise ValueError(f'{name} must be between 0 and 100')
            object.__setattr__(self, name, value)
        speed = float(self.walk_speed)
        if not 1.0 <= speed <= 500.0:
            raise ValueError('walk_speed must be between 1 and 500')
        object.__setattr__(self, 'walk_speed', speed)


@dataclass(frozen=True, slots=True)
class PetVisualTheme:
    '''Optional pet-specific accents; application chrome remains brand-owned.'''

    accent: str = '#5B8DEF'
    warm_accent: str = '#F2A65A'
    stage_light: str = '#F4F7FB'
    stage_dark: str = '#202734'

    def __post_init__(self) -> None:
        for name in ('accent', 'warm_accent', 'stage_light', 'stage_dark'):
            value = str(getattr(self, name)).strip().upper()
            if not re.fullmatch(r'#[0-9A-F]{6}', value):
                raise ValueError(f'{name} must be a six-digit hex colour')
            object.__setattr__(self, name, value)


@dataclass(frozen=True, slots=True)
class PetFrame:
    path: str
    duration_ms: int
    source_rect: tuple[int, int, int, int] | None = None

    def __post_init__(self) -> None:
        path = normalise_resource_path(self.path)
        if PurePosixPath(path).suffix.casefold() != '.png':
            raise ValueError('Pet animation frames must be PNG files')
        duration = int(self.duration_ms)
        if not 50 <= duration <= 10_000:
            raise ValueError('Frame duration must be between 50 and 10000 ms')
        source_rect = self.source_rect
        if source_rect is not None:
            try:
                x, y, width, height = (int(value) for value in source_rect)
            except (TypeError, ValueError) as error:
                raise ValueError('source_rect must contain x, y, width and height') from error
            if x < 0 or y < 0 or width <= 0 or height <= 0:
                raise ValueError('source_rect must describe a positive image region')
            source_rect = (x, y, width, height)
        object.__setattr__(self, 'path', path)
        object.__setattr__(self, 'duration_ms', duration)
        object.__setattr__(self, 'source_rect', source_rect)


@dataclass(frozen=True, slots=True)
class PetAction:
    action_id: str
    frames: tuple[PetFrame, ...]
    loop: bool = False

    def __post_init__(self) -> None:
        action_id = _normalise_action_id(self.action_id)
        frames = tuple(self.frames)
        if not frames:
            raise ValueError('Pet action must contain at least one frame')
        if len(frames) > 300:
            raise ValueError('Pet action cannot contain more than 300 frames')
        if not all(isinstance(frame, PetFrame) for frame in frames):
            raise TypeError('Pet action frames must be PetFrame values')
        object.__setattr__(self, 'action_id', action_id)
        object.__setattr__(self, 'frames', frames)
        object.__setattr__(self, 'loop', bool(self.loop))


@dataclass(frozen=True, slots=True)
class PetPackManifest:
    '''Validated immutable description of one official pet resource pack.'''

    schema_version: int
    pet_id: str
    display_name: str
    pack_version: str
    min_app_version: str
    author: str
    license: str
    canvas_size: tuple[int, int]
    default_scale: int
    personality: PetPersonality
    actions: Mapping[str, PetAction]
    event_bindings: Mapping[str, str]
    attachment_points: Mapping[str, tuple[int, int]] = field(default_factory=dict)
    appearance_rules: Mapping[str, Any] = field(default_factory=dict)
    sound_rules: Mapping[str, str] = field(default_factory=dict)
    preview_path: str = 'preview.png'
    visual_theme: PetVisualTheme = field(default_factory=PetVisualTheme)
    asset_scale: int = 1

    def __post_init__(self) -> None:
        schema_version = int(self.schema_version)
        if schema_version not in SUPPORTED_PET_PACK_SCHEMAS:
            raise ValueError(f'Unsupported pet pack schema: {self.schema_version}')
        pet_id = str(self.pet_id).strip().casefold()
        if not PET_ID_PATTERN.fullmatch(pet_id):
            raise ValueError(f'Invalid pet identifier: {self.pet_id!r}')
        display_name = str(self.display_name).strip()
        if not display_name or len(display_name) > 80:
            raise ValueError('Pet display name must contain 1 to 80 characters')
        author = str(self.author).strip()
        license_name = str(self.license).strip()
        if not author or len(author) > 120 or not license_name or len(license_name) > 80:
            raise ValueError('Pet author and license must be short non-empty values')
        try:
            width, height = (int(value) for value in self.canvas_size)
        except (TypeError, ValueError) as error:
            raise ValueError('canvas_size must contain width and height') from error
        if not (1 <= width <= 2048 and 1 <= height <= 2048):
            raise ValueError('Pet canvas dimensions must be between 1 and 2048')
        scale = int(self.default_scale)
        if not 25 <= scale <= 400:
            raise ValueError('default_scale must be between 25 and 400')
        asset_scale = int(self.asset_scale)
        if asset_scale not in {1, 2}:
            raise ValueError('asset_scale must be 1 or 2')
        if not isinstance(self.visual_theme, PetVisualTheme):
            raise TypeError('visual_theme must be a PetVisualTheme value')

        actions = {_normalise_action_id(key): value for key, value in self.actions.items()}
        if any(not isinstance(value, PetAction) for value in actions.values()):
            raise TypeError('actions must contain PetAction values')
        if any(key != value.action_id for key, value in actions.items()):
            raise ValueError('Action map keys must match action identifiers')
        missing = REQUIRED_ACTIONS.difference(actions)
        if missing:
            missing_text = ', '.join(sorted(missing))
            raise ValueError(f'Pet pack is missing required actions: {missing_text}')

        bindings: dict[str, str] = {}
        for event_kind, action_id in self.event_bindings.items():
            event = _normalise_event_kind(event_kind)
            action = _normalise_action_id(action_id)
            if action not in actions:
                raise ValueError(f'Event {event!r} refers to missing action {action!r}')
            bindings[event] = action

        points: dict[str, tuple[int, int]] = {}
        for slot, raw_point in self.attachment_points.items():
            if slot not in APPEARANCE_SLOTS:
                raise ValueError(f'Unsupported appearance slot: {slot}')
            try:
                x, y = (int(value) for value in raw_point)
            except (TypeError, ValueError) as error:
                raise ValueError(f'Invalid attachment point for {slot}') from error
            if not (0 <= x <= width and 0 <= y <= height):
                raise ValueError(f'Attachment point for {slot} is outside the canvas')
            points[slot] = (x, y)

        sounds: dict[str, str] = {}
        for event_kind, raw_path in self.sound_rules.items():
            event = _normalise_event_kind(event_kind)
            path = normalise_resource_path(raw_path)
            if PurePosixPath(path).suffix.casefold() != '.wav':
                raise ValueError('Pet sounds must be WAV files')
            sounds[event] = path
        preview = normalise_resource_path(self.preview_path)
        if PurePosixPath(preview).suffix.casefold() != '.png':
            raise ValueError('Pet preview must be a PNG file')

        object.__setattr__(self, 'schema_version', schema_version)
        object.__setattr__(self, 'pet_id', pet_id)
        object.__setattr__(self, 'display_name', display_name)
        object.__setattr__(self, 'author', author)
        object.__setattr__(self, 'license', license_name)
        object.__setattr__(self, 'canvas_size', (width, height))
        object.__setattr__(self, 'default_scale', scale)
        object.__setattr__(self, 'asset_scale', asset_scale)
        object.__setattr__(self, 'actions', MappingProxyType(actions))
        object.__setattr__(self, 'event_bindings', MappingProxyType(bindings))
        object.__setattr__(self, 'attachment_points', MappingProxyType(points))
        object.__setattr__(self, 'appearance_rules', _freeze(self.appearance_rules))
        object.__setattr__(self, 'sound_rules', MappingProxyType(sounds))
        object.__setattr__(self, 'preview_path', preview)

    def action_for_event(self, event_kind: str) -> PetAction:
        '''Resolve an event and safely fall back to the required idle action.'''

        kind = _normalise_event_kind(event_kind)
        action_id = self.event_bindings.get(kind)
        if action_id is None and kind.startswith('autonomous.'):
            action_id = kind.removeprefix('autonomous.')
        if action_id is None:
            action_id = _DEFAULT_ACTION_BY_EVENT.get(kind, kind)
        return self.actions.get(action_id, self.actions['idle'])


_DEFAULT_ACTION_BY_EVENT = {
    'click': 'click_reaction',
    'right_click': 'right_click_reaction',
    'drag.hold': 'drag_hold',
    'drag.release': 'drag_release',
    'break.due': 'rest_prompt',
    'rest.prompt': 'rest_prompt',
    'rest.sleep': 'sleep',
    'autonomous.move': 'move',
    'autonomous.idle': 'idle',
}


@dataclass(frozen=True, slots=True)
class PetEvent:
    '''One immutable semantic event sent to the companion state machine.'''

    kind: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    priority: PetEventPriority | int | None = None
    occurred_at: float = 0.0

    def __post_init__(self) -> None:
        kind = _normalise_event_kind(self.kind)
        expected = priority_for_event_kind(kind)
        if self.priority is not None and PetEventPriority(int(self.priority)) != expected:
            raise ValueError('Pet event priority is fixed by its semantic kind')
        occurred_at = float(self.occurred_at)
        if occurred_at < 0:
            raise ValueError('occurred_at cannot be negative')
        object.__setattr__(self, 'kind', kind)
        object.__setattr__(self, 'payload', _freeze(self.payload))
        object.__setattr__(self, 'priority', expected)
        object.__setattr__(self, 'occurred_at', occurred_at)


@dataclass(frozen=True, slots=True)
class PetAppearance:
    '''Semantic appearance slots independent of animal anatomy.'''

    headwear: str = ''
    neckwear: str = ''
    bodywear: str = ''
    held_item: str = ''
    scene: str = ''
    effect: str = ''


@dataclass(frozen=True, slots=True)
class PetBehavior:
    action_id: str = 'idle'
    event_kind: str = 'autonomous.idle'
    priority: PetEventPriority = PetEventPriority.AUTONOMOUS
    started_at: float = 0.0


@dataclass(frozen=True, slots=True)
class PetState:
    '''Immutable runtime projection for one active desktop companion.'''

    pet_id: str
    behavior: PetBehavior = field(default_factory=PetBehavior)
    appearance: PetAppearance = field(default_factory=PetAppearance)
    enabled: bool = True
    visible: bool = True
    bubble_visible: bool = False
    suppressed_by: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        pet_id = str(self.pet_id).strip().casefold()
        if not PET_ID_PATTERN.fullmatch(pet_id):
            raise ValueError(f'Invalid pet identifier: {self.pet_id!r}')
        object.__setattr__(self, 'pet_id', pet_id)
        reasons = tuple(dict.fromkeys(str(reason) for reason in self.suppressed_by if reason))
        object.__setattr__(self, 'suppressed_by', reasons)


@dataclass(frozen=True, slots=True)
class PetCatalogEntry:
    pet_id: str
    display_name: str
    pack_version: str
    preview_path: str
