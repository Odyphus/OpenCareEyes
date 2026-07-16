'''Discovery and validation for bundled declaration-only pet packs.'''

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any

from PySide6.QtGui import QImageReader

from opencareyes.constants import APP_VERSION
from opencareyes.domain.pet import (
    APPEARANCE_SLOTS,
    PET_ID_PATTERN,
    PetAction,
    PetCatalogEntry,
    PetFrame,
    PetPackManifest,
    PetPersonality,
    PetVisualTheme,
    normalise_resource_path,
)

ALLOWED_RESOURCE_SUFFIXES = frozenset({'.png', '.wav', '.json'})
MAX_MANIFEST_BYTES = 256 * 1024
MAX_RESOURCE_BYTES = 16 * 1024 * 1024
MAX_PACK_BYTES = 64 * 1024 * 1024
MAX_PACK_FILES = 2_000
MAX_IMAGE_DIMENSION = 4_096
MAX_IMAGE_PIXELS = 2_048 * 2_048


class PetPackError(ValueError):
    '''Base error for a pet pack that cannot safely be loaded.'''


class PetPackNotFoundError(PetPackError):
    pass


class PetPackValidationError(PetPackError):
    pass


class PetPackRegistry:
    '''Load only validated resources rooted below the configured pets folder.'''

    def __init__(self, root: str | Path, app_version: str = APP_VERSION):
        self._root = Path(root)
        self._app_version = str(app_version)
        self._cache: dict[str, PetPackManifest] = {}
        self._errors: dict[str, str] = {}

    @property
    def root(self) -> Path:
        return self._root

    @property
    def errors(self) -> Mapping[str, str]:
        return MappingProxyType(dict(self._errors))

    def discover(self) -> tuple[PetPackManifest, ...]:
        '''Return all valid packs; invalid siblings are isolated and reported.'''

        manifests: list[PetPackManifest] = []
        self._errors.clear()
        if not self._root.is_dir():
            return ()
        for candidate in sorted(self._root.iterdir(), key=lambda item: item.name.casefold()):
            if not candidate.is_dir() or not PET_ID_PATTERN.fullmatch(candidate.name):
                continue
            try:
                manifests.append(self.load(candidate.name, use_cache=False))
            except PetPackError as error:
                self._errors[candidate.name] = str(error)
        return tuple(manifests)

    def available_pets(self) -> tuple[PetCatalogEntry, ...]:
        return tuple(
            PetCatalogEntry(
                pet_id=manifest.pet_id,
                display_name=manifest.display_name,
                pack_version=manifest.pack_version,
                preview_path=manifest.preview_path,
            )
            for manifest in self.discover()
        )

    def get(self, pet_id: str) -> PetPackManifest:
        return self.load(pet_id)

    def load(self, pet_id: str, *, use_cache: bool = True) -> PetPackManifest:
        normalised_id = str(pet_id).strip().casefold()
        if not PET_ID_PATTERN.fullmatch(normalised_id):
            raise PetPackNotFoundError('Invalid pet identifier')
        if use_cache and normalised_id in self._cache:
            return self._cache[normalised_id]
        if not use_cache:
            self._cache.pop(normalised_id, None)
        pack_dir = self._root / normalised_id
        if not pack_dir.is_dir() or pack_dir.is_symlink():
            raise PetPackNotFoundError(f'Pet pack not found: {normalised_id}')
        manifest_path = pack_dir / 'manifest.json'
        if not manifest_path.is_file() or manifest_path.is_symlink():
            raise PetPackValidationError('Pet pack manifest.json is missing')
        try:
            if manifest_path.stat().st_size > MAX_MANIFEST_BYTES:
                raise PetPackValidationError('Pet pack manifest is too large')
            raw = json.loads(
                manifest_path.read_text(encoding='utf-8'),
                object_pairs_hook=self._unique_object,
            )
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise PetPackValidationError('Pet pack manifest is not valid UTF-8 JSON') from error
        if not isinstance(raw, dict):
            raise PetPackValidationError('Pet pack manifest must be a JSON object')
        self._reject_network_values(raw)
        try:
            manifest = self._parse_manifest(raw)
        except (KeyError, TypeError, ValueError) as error:
            raise PetPackValidationError(str(error)) from error
        if manifest.pet_id != normalised_id:
            raise PetPackValidationError('Manifest pet_id must match its directory name')
        self._validate_versions(manifest)
        self._validate_files(pack_dir, manifest)
        self._cache[normalised_id] = manifest
        return manifest

    def resolve_action(self, pet: str | PetPackManifest, event_kind: str) -> PetAction:
        manifest = self.load(pet) if isinstance(pet, str) else pet
        return manifest.action_for_event(event_kind)

    def resolve_resource(self, pet_id: str, resource_path: str) -> Path:
        manifest = self.load(pet_id)
        return self._resource_file(self._root / manifest.pet_id, resource_path)

    def invalidate(self, pet_id: str | None = None) -> None:
        if pet_id is None:
            self._cache.clear()
        else:
            self._cache.pop(str(pet_id).strip().casefold(), None)

    @staticmethod
    def _reject_network_values(value: Any) -> None:
        if isinstance(value, str) and re.search(r'(?i)(?:https?|ftp|file)://', value):
            raise PetPackValidationError('Pet packs cannot contain network or file URLs')
        if isinstance(value, Mapping):
            for key, item in value.items():
                PetPackRegistry._reject_network_values(key)
                PetPackRegistry._reject_network_values(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                PetPackRegistry._reject_network_values(item)

    @staticmethod
    def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise PetPackValidationError(f'Duplicate manifest field: {key}')
            result[key] = value
        return result

    @staticmethod
    def _parse_manifest(raw: dict[str, Any]) -> PetPackManifest:
        allowed = {
            'schema_version', 'pet_id', 'display_name', 'pack_version',
            'min_app_version', 'author', 'license', 'canvas_size',
            'default_scale', 'personality', 'actions', 'event_bindings',
            'attachment_points', 'appearance_rules', 'sound_rules', 'preview_path',
            'visual_theme', 'asset_scale',
        }
        unknown = set(raw).difference(allowed)
        if unknown:
            unknown_text = ', '.join(sorted(unknown))
            raise ValueError(f'Unknown manifest fields: {unknown_text}')
        personality_raw = raw['personality']
        if not isinstance(personality_raw, dict):
            raise TypeError('personality must be an object')
        personality_fields = {
            'activity', 'curiosity', 'playfulness', 'sleepiness',
            'sociability', 'walk_speed',
        }
        if set(personality_raw).difference(personality_fields):
            raise ValueError('personality contains unsupported fields')
        personality = PetPersonality(
            activity=personality_raw.get('activity', 50),
            curiosity=personality_raw.get('curiosity', 50),
            playfulness=personality_raw.get('playfulness', 50),
            sleepiness=personality_raw.get('sleepiness', 50),
            sociability=personality_raw.get('sociability', 50),
            walk_speed=personality_raw.get('walk_speed', 32.0),
        )
        actions_raw = raw['actions']
        if not isinstance(actions_raw, dict) or len(actions_raw) > 100:
            raise TypeError('actions must be an object with no more than 100 entries')
        actions: dict[str, PetAction] = {}
        total_frames = 0
        for action_id, action_raw in actions_raw.items():
            if not isinstance(action_raw, dict):
                raise TypeError(f'Action {action_id!r} must be an object')
            if 'loop' in action_raw and not isinstance(action_raw['loop'], bool):
                raise TypeError(f'Action {action_id!r} loop must be a boolean')
            frames_raw = action_raw.get('frames')
            if not isinstance(frames_raw, list):
                raise TypeError(f'Action {action_id!r} frames must be a list')
            frames = []
            for frame_raw in frames_raw:
                if not isinstance(frame_raw, dict):
                    raise TypeError('Each frame must be an object')
                allowed_frame_fields = {'path', 'duration_ms'}
                if int(raw['schema_version']) >= 2:
                    allowed_frame_fields.add('source_rect')
                if not {'path', 'duration_ms'}.issubset(frame_raw) or set(
                    frame_raw
                ).difference(allowed_frame_fields):
                    raise TypeError(
                        'Each frame must contain path, duration_ms and optional source_rect'
                    )
                source_rect = frame_raw.get('source_rect')
                if source_rect is not None and (
                    not isinstance(source_rect, list) or len(source_rect) != 4
                ):
                    raise TypeError('source_rect must be a four-item list')
                frames.append(
                    PetFrame(
                        frame_raw['path'],
                        frame_raw['duration_ms'],
                        tuple(source_rect) if source_rect is not None else None,
                    )
                )
            total_frames += len(frames)
            if int(raw['schema_version']) >= 2 and len(frames) > 60:
                raise ValueError('A schema-v2 action cannot exceed 60 frames')
            extra = set(action_raw).difference({'frames', 'loop'})
            if extra:
                raise ValueError(f'Action {action_id!r} contains unsupported fields')
            actions[str(action_id)] = PetAction(
                str(action_id), tuple(frames), bool(action_raw.get('loop', False))
            )
        if int(raw['schema_version']) >= 2 and total_frames > 256:
            raise ValueError('A schema-v2 pet pack cannot exceed 256 action frames')
        bindings = raw.get('event_bindings', {})
        points = raw.get('attachment_points', {})
        appearance = raw.get('appearance_rules', {})
        sounds = raw.get('sound_rules', {})
        if not all(isinstance(value, dict) for value in (bindings, points, appearance, sounds)):
            raise TypeError('Pet mappings must be JSON objects')
        visual_theme_raw = raw.get('visual_theme', {})
        if not isinstance(visual_theme_raw, dict):
            raise TypeError('visual_theme must be an object')
        visual_theme_fields = {
            'accent', 'warm_accent', 'stage_light', 'stage_dark',
        }
        if set(visual_theme_raw).difference(visual_theme_fields):
            raise ValueError('visual_theme contains unsupported fields')
        visual_theme = PetVisualTheme(**visual_theme_raw)
        canvas_size = raw['canvas_size']
        if not isinstance(canvas_size, list) or len(canvas_size) != 2:
            raise TypeError('canvas_size must be a two-item list')
        return PetPackManifest(
            schema_version=raw['schema_version'],
            pet_id=raw['pet_id'],
            display_name=raw['display_name'],
            pack_version=raw['pack_version'],
            min_app_version=raw['min_app_version'],
            author=raw['author'],
            license=raw['license'],
            canvas_size=tuple(canvas_size),
            default_scale=raw['default_scale'],
            personality=personality,
            actions=actions,
            event_bindings=bindings,
            attachment_points=points,
            appearance_rules=appearance,
            sound_rules=sounds,
            preview_path=raw.get('preview_path', 'preview.png'),
            visual_theme=visual_theme,
            asset_scale=raw.get('asset_scale', 1),
        )

    def _validate_versions(self, manifest: PetPackManifest) -> None:
        pack_version = self._version_tuple(manifest.pack_version, 'pack_version')
        del pack_version
        minimum = self._version_tuple(manifest.min_app_version, 'min_app_version')
        current = self._version_tuple(self._app_version, 'application version')
        if minimum > current:
            raise PetPackValidationError(
                f'Pet pack requires OpenCareEyes {manifest.min_app_version} or newer'
            )

    @staticmethod
    def _version_tuple(value: str, field_name: str) -> tuple[int, ...]:
        text = str(value).strip()
        if not re.fullmatch(r'[0-9]+(?:\.[0-9]+){0,3}', text):
            raise PetPackValidationError(f'{field_name} must be a numeric release version')
        values = tuple(int(part) for part in text.split('.'))
        return values + (0,) * (4 - len(values))

    def _validate_files(self, pack_dir: Path, manifest: PetPackManifest) -> None:
        total_size = 0
        file_count = 0
        for entry in pack_dir.rglob('*'):
            if entry.is_symlink():
                raise PetPackValidationError('Pet packs cannot contain symbolic links')
            if not entry.is_file():
                continue
            file_count += 1
            if file_count > MAX_PACK_FILES:
                raise PetPackValidationError('Pet pack contains too many files')
            suffix = entry.suffix.casefold()
            if suffix not in ALLOWED_RESOURCE_SUFFIXES:
                raise PetPackValidationError(
                    f'Unsupported pet resource extension: {suffix}'
                )
            size = entry.stat().st_size
            if size > MAX_RESOURCE_BYTES and entry.name != 'manifest.json':
                raise PetPackValidationError(f'Pet resource is too large: {entry.name}')
            total_size += size
            if total_size > MAX_PACK_BYTES:
                raise PetPackValidationError('Pet pack exceeds the size limit')
            if suffix == '.png':
                self._validate_png(entry)

        references = [manifest.preview_path]
        references.extend(frame.path for action in manifest.actions.values() for frame in action.frames)
        references.extend(manifest.sound_rules.values())
        for condition, raw_slots in manifest.appearance_rules.items():
            if not isinstance(condition, str) or not isinstance(raw_slots, Mapping):
                raise PetPackValidationError('appearance_rules must map conditions to slot objects')
            for slot, raw_path in raw_slots.items():
                if slot not in APPEARANCE_SLOTS:
                    raise PetPackValidationError(f'Unsupported appearance slot: {slot}')
                path = normalise_resource_path(str(raw_path))
                if PurePosixPath(path).suffix.casefold() != '.png':
                    raise PetPackValidationError('Pet appearance resources must be PNG files')
                references.append(path)
        for resource_path in references:
            self._resource_file(pack_dir, resource_path)
        for action in manifest.actions.values():
            for frame in action.frames:
                if frame.source_rect is None:
                    continue
                resource = self._resource_file(pack_dir, frame.path)
                reader = QImageReader(str(resource))
                reader.setDecideFormatFromContent(True)
                size = reader.size()
                x, y, width, height = frame.source_rect
                if (
                    not size.isValid()
                    or x + width > size.width()
                    or y + height > size.height()
                ):
                    raise PetPackValidationError(
                        f'Frame source_rect leaves its atlas: {frame.path}'
                    )

    @staticmethod
    def _resource_file(pack_dir: Path, resource_path: str) -> Path:
        try:
            relative = normalise_resource_path(resource_path)
        except ValueError as error:
            raise PetPackValidationError(str(error)) from error
        root = pack_dir.resolve()
        candidate = root.joinpath(*PurePosixPath(relative).parts).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as error:
            raise PetPackValidationError('Resource path leaves the pet pack') from error
        if not candidate.is_file() or candidate.is_symlink():
            raise PetPackValidationError(f'Pet resource is missing: {relative}')
        if candidate.suffix.casefold() not in ALLOWED_RESOURCE_SUFFIXES:
            raise PetPackValidationError('Unsupported pet resource extension')
        return candidate

    @staticmethod
    def _validate_png(path: Path) -> None:
        reader = QImageReader(str(path))
        reader.setDecideFormatFromContent(True)
        size = reader.size()
        image_format = bytes(reader.format()).lower()
        if image_format != b'png' or not size.isValid():
            raise PetPackValidationError(f'Pet PNG is invalid: {path.name}')
        width = int(size.width())
        height = int(size.height())
        if (
            width > MAX_IMAGE_DIMENSION
            or height > MAX_IMAGE_DIMENSION
            or width * height > MAX_IMAGE_PIXELS
        ):
            raise PetPackValidationError(
                f'Pet PNG dimensions are too large: {path.name}'
            )
