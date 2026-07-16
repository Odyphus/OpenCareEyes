'''Frame animation runtime shared by the desktop companion surface.

The animator deliberately knows nothing about breaks, focus sessions or the
application state. It consumes declarative pet-pack actions and emits a single
image at a time. High-frequency frame updates therefore stay out of AppState.
'''

from __future__ import annotations

import math
import time
from collections import OrderedDict
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QObject, QTimer, Signal, Slot
from PySide6.QtGui import QImage


class PetAnimator(QObject):
    '''Advance frames for one pet action using a single QTimer.'''

    frame_changed = Signal(object)
    action_changed = Signal(str)
    animation_finished = Signal(str)

    def __init__(
        self,
        repository=None,
        parent=None,
        *,
        cache_limit: int = 64,
        cache_limit_bytes: int = 32 * 1024 * 1024,
        clock: Callable[[], float] | None = None,
    ):
        super().__init__(parent)
        self._repository = repository
        self._pet_id = ''
        self._manifest = None
        self._action = None
        self._action_id = ''
        self._frame_index = 0
        self._action_finished = False
        self._surface_visible = False
        self._reduced_motion = False
        self._clock = clock or time.monotonic
        self._frame_deadline: float | None = None
        self._cache_limit = max(1, int(cache_limit))
        self._cache_limit_bytes = max(1, int(cache_limit_bytes))
        self._cache_bytes = 0
        self._image_cache: OrderedDict[tuple[Any, ...], QImage] = OrderedDict()

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._advance)
        ready = getattr(repository, 'resource_ready', None)
        if ready is not None:
            ready.connect(self._on_resource_ready)

    @property
    def action_id(self) -> str:
        return self._action_id

    @property
    def frame_index(self) -> int:
        return self._frame_index

    @property
    def is_running(self) -> bool:
        return self._timer.isActive()

    @property
    def timer(self) -> QTimer:
        '''Expose the shared timer for diagnostics and deterministic tests.'''

        return self._timer

    def set_pack(self, pet_id: str, manifest) -> None:
        '''Replace the active declarative pack without starting an action.'''

        changed = str(pet_id) != self._pet_id or manifest is not self._manifest
        self._pet_id = str(pet_id)
        self._manifest = manifest
        if changed:
            self.clear_cache()
            self.stop(clear_frame=True)

    def set_surface_visible(self, visible: bool) -> None:
        '''Start or suspend frame advancement with the top-level surface.'''

        visible = bool(visible)
        if visible == self._surface_visible:
            return
        self._surface_visible = visible
        if visible:
            self._schedule_current_frame()
        else:
            self._timer.stop()
            self._frame_deadline = None

    def set_reduced_motion(self, reduced: bool) -> None:
        '''Snap to a static frame and stop animation when requested.'''

        reduced = bool(reduced)
        if reduced == self._reduced_motion:
            return
        self._reduced_motion = reduced
        self._timer.stop()
        self._frame_deadline = None
        if self._action is None:
            return
        if reduced:
            self._frame_index = self._static_frame_index(self._action)
            self._emit_current_frame()
        else:
            self._schedule_current_frame()

    def play(self, action_id: str, action=None, *, restart: bool = False) -> bool:
        '''Play an action object or resolve one from the active manifest.

        PetAction is consumed through attributes so immutable dataclasses and
        small test doubles work equally well. Missing assets emit None and the
        surface paints its built-in static fallback.
        '''

        action_id = str(action_id)
        resolved = action if action is not None else self._resolve_action(action_id)
        if resolved is None:
            return False

        resolved_id = str(getattr(resolved, 'action_id', action_id) or action_id)
        if not restart and resolved is self._action and resolved_id == self._action_id:
            return True

        self._timer.stop()
        self._action = resolved
        self._action_id = resolved_id
        self._action_finished = False
        self._frame_deadline = None
        self._frame_index = (
            self._static_frame_index(resolved) if self._reduced_motion else 0
        )
        self.action_changed.emit(self._action_id)
        self._emit_current_frame()
        self._schedule_current_frame()
        return True

    def stop(self, *, clear_frame: bool = False) -> None:
        self._timer.stop()
        self._action = None
        self._action_id = ''
        self._frame_index = 0
        self._action_finished = False
        self._frame_deadline = None
        if clear_frame:
            self.frame_changed.emit(None)

    def clear_cache(self) -> None:
        self._image_cache.clear()
        self._cache_bytes = 0

    def _resolve_action(self, action_id: str):
        actions = getattr(self._manifest, 'actions', None)
        if isinstance(actions, Mapping):
            action = actions.get(action_id)
            if action is not None:
                return action

        if self._repository is not None:
            for method_name in ('get_action', 'action'):
                method = getattr(self._repository, method_name, None)
                if method is None:
                    continue
                try:
                    action = method(self._pet_id, action_id)
                except (KeyError, TypeError, ValueError):
                    continue
                if action is not None:
                    return action
        return None

    @staticmethod
    def _frames(action) -> tuple[Any, ...]:
        frames = getattr(action, 'frames', ())
        try:
            return tuple(frames)
        except TypeError:
            return ()

    @classmethod
    def _static_frame_index(cls, action) -> int:
        frames = cls._frames(action)
        if not frames:
            return 0
        requested = int(getattr(action, 'static_frame', 0) or 0)
        return max(0, min(requested, len(frames) - 1))

    @staticmethod
    def _frame_duration(frame) -> int:
        duration = getattr(frame, 'duration_ms', 83)
        try:
            # Desktop sprites are intentionally capped at 20 fps.  Keeping the
            # clamp here avoids mutating the immutable pack declaration.
            return max(50, int(duration))
        except (TypeError, ValueError):
            return 83

    def _schedule_current_frame(self) -> None:
        if (
            not self._surface_visible
            or self._reduced_motion
            or self._action is None
            or self._action_finished
        ):
            self._timer.stop()
            return
        frames = self._frames(self._action)
        if len(frames) <= 1:
            self._timer.stop()
            self._frame_deadline = None
            return
        frame = frames[min(self._frame_index, len(frames) - 1)]
        now = self._clock()
        if self._frame_deadline is None:
            self._frame_deadline = now + self._frame_duration(frame) / 1000.0
        remaining_ms = max(1, math.ceil((self._frame_deadline - now) * 1000.0))
        self._timer.start(remaining_ms)

    def _advance(self) -> None:
        if not self._surface_visible or self._reduced_motion or self._action is None:
            self._timer.stop()
            self._frame_deadline = None
            return
        frames = self._frames(self._action)
        if len(frames) <= 1:
            self._timer.stop()
            self._frame_deadline = None
            return
        if self._frame_deadline is None:
            self._schedule_current_frame()
            return

        now = self._clock()
        if now < self._frame_deadline:
            if self.sender() is self._timer:
                self._schedule_current_frame()
                return
            # Keep the existing deterministic private-step behavior used by
            # UI tests and diagnostics; real timer delivery still obeys the
            # monotonic deadline above.
            now = self._frame_deadline

        looping = bool(getattr(self._action, 'loop', False))
        if looping:
            cycle_seconds = sum(self._frame_duration(frame) for frame in frames) / 1000.0
            overdue = now - self._frame_deadline
            if cycle_seconds > 0 and overdue >= cycle_seconds:
                self._frame_deadline += int(overdue // cycle_seconds) * cycle_seconds

        changed = False
        while self._frame_deadline is not None and now >= self._frame_deadline:
            next_index = self._frame_index + 1
            if next_index >= len(frames):
                if looping:
                    next_index = 0
                else:
                    self._frame_index = len(frames) - 1
                    if changed:
                        self._emit_current_frame()
                    self._action_finished = True
                    self._frame_deadline = None
                    self.animation_finished.emit(self._action_id)
                    self._timer.stop()
                    return

            self._frame_index = next_index
            changed = True
            self._frame_deadline += self._frame_duration(frames[next_index]) / 1000.0

        if changed:
            # Only publish the frame that is current now; expired intermediate
            # frames are deliberately skipped after a busy main-thread spell.
            self._emit_current_frame()
        self._schedule_current_frame()

    def _emit_current_frame(self) -> None:
        if self._action is None:
            self.frame_changed.emit(None)
            return
        frames = self._frames(self._action)
        if not frames:
            self.frame_changed.emit(None)
            return
        index = max(0, min(self._frame_index, len(frames) - 1))
        self.frame_changed.emit(self._load_image(frames[index]))

    def _load_image(self, frame) -> QImage | None:
        direct_image = getattr(frame, 'image', None)
        if isinstance(direct_image, QImage):
            return self._render_frame_image(QImage(direct_image), frame)
        if isinstance(frame, QImage):
            return QImage(frame)

        path_value = getattr(frame, 'path', None)
        if path_value is None and isinstance(frame, (str, Path)):
            path_value = frame
        if not path_value:
            return None

        path = str(path_value)
        source_key = (self._pet_id, path, 'source')
        source = self._cache_get(source_key)
        if source is None:
            source = self._load_from_repository(path)
            if source is None:
                source = QImage(path)
            if source.isNull():
                return None
            source = QImage(source)
            self._cache_put(source_key, source)

        source_rect = self._source_rect(frame)
        requested_dpr = self._requested_dpr(frame, source)
        if source_rect is None and requested_dpr == round(source.devicePixelRatio(), 4):
            return QImage(source)

        rendered_key = (
            self._pet_id,
            path,
            'frame',
            requested_dpr,
            source_rect,
        )
        rendered = self._cache_get(rendered_key)
        if rendered is not None:
            return QImage(rendered)

        rendered = self._render_frame_image(source, frame, requested_dpr=requested_dpr)
        if rendered is None or rendered.isNull():
            return None
        self._cache_put(rendered_key, rendered, preserve={source_key})
        return QImage(rendered)

    @staticmethod
    def _source_rect(frame) -> tuple[int, int, int, int] | None:
        value = getattr(frame, 'source_rect', None)
        if value is None:
            return None
        try:
            x, y, width, height = (int(part) for part in value)
        except (TypeError, ValueError):
            return None
        if width <= 0 or height <= 0:
            return None
        return x, y, width, height

    @staticmethod
    def _requested_dpr(frame, image: QImage) -> float:
        value = getattr(frame, 'device_pixel_ratio', None)
        if value is None:
            value = getattr(frame, 'dpr', None)
        try:
            dpr = float(value) if value is not None else float(image.devicePixelRatio())
        except (TypeError, ValueError):
            dpr = float(image.devicePixelRatio())
        return round(max(0.01, dpr), 4)

    def _render_frame_image(
        self,
        source: QImage,
        frame,
        *,
        requested_dpr: float | None = None,
    ) -> QImage | None:
        source_rect = self._source_rect(frame)
        if source_rect is None:
            rendered = QImage(source)
        else:
            rendered = source.copy(*source_rect)
        if rendered.isNull():
            return None
        dpr = requested_dpr or self._requested_dpr(frame, source)
        rendered.setDevicePixelRatio(dpr)
        return rendered

    def _cache_get(self, key: tuple[Any, ...]) -> QImage | None:
        cached = self._image_cache.pop(key, None)
        if cached is None:
            return None
        self._image_cache[key] = cached
        return cached

    def _cache_put(
        self,
        key: tuple[Any, ...],
        image: QImage,
        *,
        preserve: set[tuple[Any, ...]] | None = None,
    ) -> None:
        previous = self._image_cache.pop(key, None)
        if previous is not None:
            self._cache_bytes = max(0, self._cache_bytes - previous.sizeInBytes())

        stored = QImage(image)
        self._image_cache[key] = stored
        self._cache_bytes += stored.sizeInBytes()
        while (
            len(self._image_cache) > self._cache_limit
            or self._cache_bytes > self._cache_limit_bytes
        ):
            evict_key = next(
                (candidate for candidate in self._image_cache if candidate not in (preserve or set())),
                None,
            )
            if evict_key is None:
                break
            evicted = self._image_cache.pop(evict_key)
            self._cache_bytes = max(0, self._cache_bytes - evicted.sizeInBytes())

    def _load_from_repository(self, path: str) -> QImage | None:
        if self._repository is None:
            return None
        loader = getattr(self._repository, 'load_frame', None)
        try:
            if loader is not None:
                loaded = loader(self._pet_id, path)
            else:
                resolver = getattr(self._repository, 'resolve_resource', None)
                if resolver is None:
                    return None
                loaded = resolver(self._pet_id, path)
        except (FileNotFoundError, KeyError, OSError, TypeError, ValueError):
            return None
        if isinstance(loaded, QImage):
            return QImage(loaded)
        if loaded:
            return QImage(str(loaded))
        return None

    @Slot(str, str)
    def _on_resource_ready(self, pet_id: str, resource_path: str) -> None:
        if pet_id != self._pet_id or self._action is None:
            return
        frames = self._frames(self._action)
        if not any(str(getattr(frame, 'path', '')) == resource_path for frame in frames):
            return
        self._emit_current_frame()
