"""Low-frequency, non-persistent desktop-companion window avoidance."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QObject, QTimer, Signal

from opencareyes.platform.window_geometry import (
    MonitorGeometry,
    ScreenRect,
    WindowGeometryBackend,
    WindowGeometrySnapshot,
)

__all__ = ["MovementRequest", "WindowAvoidanceService"]


@dataclass(frozen=True, slots=True)
class MovementRequest:
    """An ephemeral move; callers must not treat it as a new user anchor."""

    position: tuple[int, int]
    reason: str


class WindowAvoidanceService(QObject):
    """Request a nearby safe position after foreground context stabilises."""

    move_requested = Signal(object)
    restore_requested = Signal()

    def __init__(
        self,
        backend: WindowGeometryBackend,
        pet_rect: Callable[[], ScreenRect],
        can_move: Callable[[], bool],
        parent: QObject | None = None,
        *,
        follow_active_monitor: Callable[[], bool] | None = None,
        avoid_windows: Callable[[], bool] | None = None,
        anchor_rect: Callable[[], ScreenRect] | None = None,
        clock: Callable[[], float] = time.monotonic,
        interval_ms: int = 1_000,
        stable_seconds: float = 2.0,
        minimum_sample_interval_seconds: float | None = None,
        margin: int = 16,
        peek_size: int = 24,
    ) -> None:
        super().__init__(parent)
        self._backend = backend
        self._pet_rect = pet_rect
        self._anchor_rect = anchor_rect or pet_rect
        self._can_move = can_move
        self._follow_active_monitor = follow_active_monitor or (lambda: True)
        self._avoid_windows = avoid_windows or (lambda: True)
        self._clock = clock
        self._stable_seconds = max(0.0, float(stable_seconds))
        if minimum_sample_interval_seconds is None:
            minimum_sample_interval_seconds = max(250, int(interval_ms)) / 1_000
        self._minimum_sample_interval_seconds = max(
            0.0,
            float(minimum_sample_interval_seconds),
        )
        self._margin = max(0, int(margin))
        self._peek_size = max(1, int(peek_size))
        self._context_key: tuple[int, str | None] | None = None
        self._stable_since = 0.0
        self._last_requested: MovementRequest | None = None
        self._last_request_observed = False
        self._temporarily_displaced = False
        self._blocked = False
        self._last_sample_at: float | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(max(250, int(interval_ms)))
        self._timer.timeout.connect(self.poll)

    @property
    def is_active(self) -> bool:
        return self._timer.isActive()

    @property
    def temporarily_displaced(self) -> bool:
        return self._temporarily_displaced

    def start(self) -> None:
        if not self._timer.isActive():
            self._timer.start()

    def stop(self, *, restore: bool = False) -> None:
        self._timer.stop()
        if restore and self._temporarily_displaced:
            self.restore_requested.emit()
        self._temporarily_displaced = False
        self._last_requested = None
        self._last_request_observed = False
        self._context_key = None
        self._blocked = False
        self._last_sample_at = None

    def poll(self) -> MovementRequest | None:
        """Sample once and emit at most one position/reason-only request."""

        try:
            can_move = bool(self._can_move())
        except (RuntimeError, TypeError, ValueError):
            can_move = False
        if not can_move:
            self._blocked = True
            return None

        now = float(self._clock())
        if self._blocked:
            self._blocked = False
            self._reset_observation()
            self._last_sample_at = None
        if (
            self._last_sample_at is not None
            and not self._temporarily_displaced
            and 0.0 <= now - self._last_sample_at < self._minimum_sample_interval_seconds
            and not (
                self._last_sample_at
                < self._stable_since + self._stable_seconds
                <= now
            )
        ):
            return None

        try:
            snapshot = self._backend.sample()
        except (OSError, RuntimeError, TypeError, ValueError):
            self._last_sample_at = now
            self._reset_observation()
            return None
        self._last_sample_at = now
        if not snapshot.geometry_available:
            self._reset_observation()
            return None

        context_key = (snapshot.foreground_hwnd, snapshot.active_monitor_id)
        if context_key != self._context_key:
            self._context_key = context_key
            self._stable_since = now
            self._last_requested = None
            self._last_request_observed = False
            return None
        if now - self._stable_since < self._stable_seconds:
            return None
        try:
            pet = self._pet_rect()
            anchor = self._anchor_rect()
        except (RuntimeError, TypeError, ValueError):
            return None
        if not self._can_evaluate(snapshot, anchor):
            self._context_key = None
            self._last_requested = None
            self._last_request_observed = False
            return None
        request = self._evaluate(snapshot, anchor)
        if request is None:
            self._last_requested = None
            self._last_request_observed = False
            if self._temporarily_displaced:
                self._temporarily_displaced = False
                if (pet.left, pet.top) != (anchor.left, anchor.top):
                    self.restore_requested.emit()
            return None
        if request.position == (pet.left, pet.top):
            if request == self._last_requested:
                self._last_request_observed = True
            return None
        if request == self._last_requested and not self._last_request_observed:
            return None
        self._last_requested = request
        self._last_request_observed = False
        self._temporarily_displaced = True
        self.move_requested.emit(request)
        try:
            moved = self._pet_rect()
        except (RuntimeError, TypeError, ValueError):
            moved = None
        if moved is not None and request.position == (moved.left, moved.top):
            self._last_request_observed = True
        return request

    def _reset_observation(self) -> None:
        self._context_key = None
        self._last_requested = None
        self._last_request_observed = False

    def _can_evaluate(
        self,
        snapshot: WindowGeometrySnapshot,
        anchor: ScreenRect,
    ) -> bool:
        if not anchor.is_valid or not snapshot.monitors:
            return False
        anchor_monitor = _monitor_for_rect(snapshot.monitors, anchor)
        active_monitor = _find_monitor(
            snapshot.monitors,
            snapshot.active_monitor_id,
        )
        if snapshot.active_monitor_id is not None and active_monitor is None:
            return False
        return anchor_monitor is not None or bool(
            self._follow_active_monitor() and active_monitor is not None
        )

    def _evaluate(
        self,
        snapshot: WindowGeometrySnapshot,
        pet: ScreenRect,
    ) -> MovementRequest | None:
        if not pet.is_valid or not snapshot.monitors:
            return None

        current_monitor = _monitor_for_rect(snapshot.monitors, pet)
        active_monitor = _find_monitor(
            snapshot.monitors,
            snapshot.active_monitor_id,
        )
        migrate = bool(
            self._follow_active_monitor()
            and active_monitor is not None
            and (
                current_monitor is None
                or current_monitor.monitor_id != active_monitor.monitor_id
            )
        )
        target_monitor = active_monitor if migrate else current_monitor
        if target_monitor is None:
            return None

        foregrounds = _foregrounds_for_monitor(snapshot, target_monitor)
        if not migrate:
            if not self._avoid_windows():
                return None
            intersecting = tuple(
                foreground
                for foreground in foregrounds
                if pet.intersects(foreground)
            )
            if not intersecting:
                return None
            foreground = max(
                intersecting,
                key=pet.intersection_area,
            )
        else:
            foreground = max(
                foregrounds,
                key=target_monitor.work_area.intersection_area,
                default=None,
            )

        position, edge_peek = _choose_position(
            target_monitor.work_area,
            pet,
            foreground,
            snapshot.monitors,
            margin=self._margin,
            peek_size=self._peek_size,
        )
        if position is None:
            return None
        if edge_peek:
            reason = "edge_peek"
        elif migrate:
            reason = "active_monitor"
        else:
            reason = "window_avoidance"
        return MovementRequest(position=position, reason=reason)


def _find_monitor(
    monitors: tuple[MonitorGeometry, ...],
    monitor_id: str | None,
) -> MonitorGeometry | None:
    if monitor_id is None:
        return None
    return next(
        (monitor for monitor in monitors if monitor.monitor_id == monitor_id),
        None,
    )


def _monitor_for_rect(
    monitors: tuple[MonitorGeometry, ...],
    rect: ScreenRect,
) -> MonitorGeometry | None:
    centre_x = rect.left + rect.width // 2
    centre_y = rect.top + rect.height // 2
    containing = [
        monitor
        for monitor in monitors
        if monitor.work_area.contains_point(centre_x, centre_y)
    ]
    if containing:
        return containing[0]
    best = max(
        monitors,
        key=lambda monitor: monitor.work_area.intersection_area(rect),
        default=None,
    )
    if best is None or best.work_area.intersection_area(rect) <= 0:
        return None
    return best


def _foregrounds_for_monitor(
    snapshot: WindowGeometrySnapshot,
    monitor: MonitorGeometry,
) -> tuple[ScreenRect, ...]:
    foregrounds = snapshot.foreground_rects
    if not foregrounds and snapshot.foreground_rect is not None:
        foregrounds = (snapshot.foreground_rect,)
    return tuple(
        foreground
        for foreground in foregrounds
        if foreground.intersects(monitor.work_area)
    )


def _choose_position(
    work_area: ScreenRect,
    pet: ScreenRect,
    foreground: ScreenRect | None,
    monitors: tuple[MonitorGeometry, ...],
    *,
    margin: int,
    peek_size: int,
) -> tuple[tuple[int, int] | None, bool]:
    width = pet.width
    height = pet.height
    left = work_area.left + margin
    top = work_area.top + margin
    right = max(left, work_area.right - width - margin)
    bottom = max(top, work_area.bottom - height - margin)
    corners = tuple(dict.fromkeys(((left, top), (right, top), (left, bottom), (right, bottom))))
    clear = [
        position
        for position in corners
        if foreground is None
        or not _rect_at(position, width, height).intersects(foreground)
    ]
    if clear:
        return min(clear, key=lambda position: _distance_squared(position, pet)), False

    horizontal_peek = min(peek_size, width)
    vertical_peek = min(peek_size, height)
    clamped_x = _clamp(pet.left, left, right)
    clamped_y = _clamp(pet.top, top, bottom)
    edge_positions = (
        (work_area.left - width + horizontal_peek, clamped_y),
        (work_area.right - horizontal_peek, clamped_y),
        (clamped_x, work_area.top - height + vertical_peek),
        (clamped_x, work_area.bottom - vertical_peek),
    )

    def edge_score(position: tuple[int, int]) -> tuple[int, int, int]:
        candidate = _rect_at(position, width, height)
        obstruction = (
            candidate.intersection_area(foreground) if foreground is not None else 0
        )
        visible_area = sum(
            candidate.intersection_area(monitor.work_area) for monitor in monitors
        )
        return obstruction, visible_area, _distance_squared(position, pet)

    return min(edge_positions, key=edge_score), True


def _rect_at(position: tuple[int, int], width: int, height: int) -> ScreenRect:
    x, y = position
    return ScreenRect(x, y, x + width, y + height)


def _distance_squared(position: tuple[int, int], pet: ScreenRect) -> int:
    return (position[0] - pet.left) ** 2 + (position[1] - pet.top) ** 2


def _clamp(value: int, lower: int, upper: int) -> int:
    return max(lower, min(value, upper))
