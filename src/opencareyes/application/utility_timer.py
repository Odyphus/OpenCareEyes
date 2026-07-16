'''A single, monotonic user utility timer independent from break cadence.'''

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QObject, QTimer, Signal


MAX_TIMER_SECONDS = 24 * 60 * 60


@dataclass(frozen=True, slots=True)
class UtilityTimerState:
    status: str = 'idle'
    duration_seconds: int = 0
    remaining_seconds: int = 0
    label: str = ''


class UtilityTimerService(QObject):
    '''Own exactly one user timer and emit a dedicated second tick.'''

    state_changed = Signal(object)
    tick = Signal(int)
    finished = Signal(object)

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        clock: Callable[[], float] | None = None,
    ) -> None:
        super().__init__(parent)
        self._clock = clock or time.monotonic
        self._timer = QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self.poll)
        self._state = UtilityTimerState()
        self._deadline: float | None = None
        self._paused_remaining: float | None = None
        self._last_tick: int | None = None

    @property
    def state(self) -> UtilityTimerState:
        return self._state

    @property
    def active(self) -> bool:
        return self._state.status in {'running', 'paused'}

    def start(self, duration_seconds: int, *, label: str = '') -> UtilityTimerState:
        if isinstance(duration_seconds, bool) or not isinstance(duration_seconds, int):
            raise TypeError('duration_seconds must be an integer')
        if not 1 <= duration_seconds <= MAX_TIMER_SECONDS:
            raise ValueError('duration_seconds must be between 1 and 86400')
        if not isinstance(label, str):
            raise TypeError('timer label must be a string')
        if len(label) > 100:
            raise ValueError('timer label is too long')

        self._deadline = self._clock() + duration_seconds
        self._paused_remaining = None
        self._last_tick = duration_seconds
        self._state = UtilityTimerState(
            status='running',
            duration_seconds=duration_seconds,
            remaining_seconds=duration_seconds,
            label=label,
        )
        self._timer.start()
        self.state_changed.emit(self._state)
        self.tick.emit(duration_seconds)
        return self._state

    def cancel(self) -> bool:
        if not self.active:
            return False
        self._timer.stop()
        self._deadline = None
        self._paused_remaining = None
        self._last_tick = None
        self._state = UtilityTimerState()
        self.state_changed.emit(self._state)
        return True

    def pause(self) -> bool:
        if self._state.status != 'running' or self._deadline is None:
            return False
        remaining_value = self._deadline - self._clock()
        if remaining_value <= 0:
            self.poll()
            return False
        self._paused_remaining = remaining_value
        self._deadline = None
        self._timer.stop()
        remaining = math.ceil(self._paused_remaining)
        self._state = UtilityTimerState(
            status='paused',
            duration_seconds=self._state.duration_seconds,
            remaining_seconds=remaining,
            label=self._state.label,
        )
        self._last_tick = remaining
        self.state_changed.emit(self._state)
        return True

    def resume(self) -> bool:
        if self._state.status != 'paused' or self._paused_remaining is None:
            return False
        self._deadline = self._clock() + self._paused_remaining
        self._paused_remaining = None
        self._state = UtilityTimerState(
            status='running',
            duration_seconds=self._state.duration_seconds,
            remaining_seconds=self._state.remaining_seconds,
            label=self._state.label,
        )
        self._timer.start()
        self.state_changed.emit(self._state)
        return True

    def poll(self) -> UtilityTimerState:
        if self._state.status != 'running' or self._deadline is None:
            return self._state
        remaining = math.ceil(max(0.0, self._deadline - self._clock()))
        if remaining != self._last_tick:
            self._last_tick = remaining
            self._state = UtilityTimerState(
                status='running',
                duration_seconds=self._state.duration_seconds,
                remaining_seconds=remaining,
                label=self._state.label,
            )
            self.tick.emit(remaining)
        if remaining > 0:
            return self._state

        self._timer.stop()
        self._deadline = None
        self._paused_remaining = None
        self._state = UtilityTimerState(
            status='finished',
            duration_seconds=self._state.duration_seconds,
            remaining_seconds=0,
            label=self._state.label,
        )
        self.state_changed.emit(self._state)
        self.finished.emit(self._state)
        return self._state
