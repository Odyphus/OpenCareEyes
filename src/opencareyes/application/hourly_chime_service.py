'''Low-overhead, privacy-preserving hourly chime scheduling.'''

from __future__ import annotations

import math
import re
from collections.abc import Callable
from datetime import datetime, time, timedelta

from PySide6.QtCore import QObject, QTimer, Signal


class HourlyChimeService(QObject):
    '''Request one semantic chime at most once for each wall-clock hour.'''

    chime = Signal(int, bool)

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        now: Callable[[], datetime] | None = None,
        allowed: Callable[[], bool] | None = None,
    ) -> None:
        super().__init__(parent)
        self._now = now or datetime.now
        self._allowed_provider = allowed
        self._runtime_allowed = True
        self._enabled = False
        self._sound_enabled = False
        self._quiet_start = time(23, 0)
        self._quiet_end = time(7, 0)
        self._last_hour: tuple[int, int, int, int] | None = None

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._on_timeout)

    @property
    def running(self) -> bool:
        return self._timer.isActive()

    def configure(
        self,
        enabled: bool,
        sound_enabled: bool,
        quiet_start: str | time,
        quiet_end: str | time,
    ) -> None:
        '''Update preferences without implicitly starting background work.'''

        if not isinstance(enabled, bool) or not isinstance(sound_enabled, bool):
            raise TypeError('enabled and sound_enabled must be booleans')
        parsed_start = _parse_clock_time(quiet_start)
        parsed_end = _parse_clock_time(quiet_end)
        self._enabled = enabled
        self._sound_enabled = sound_enabled
        self._quiet_start = parsed_start
        self._quiet_end = parsed_end

    def set_allowed(self, allowed: bool) -> None:
        '''Set the runtime context gate used for lock/full-screen suppression.'''

        if not isinstance(allowed, bool):
            raise TypeError('allowed must be a boolean')
        self._runtime_allowed = allowed

    def start(self) -> None:
        '''Start wall-clock scheduling; callers opt in explicitly.'''

        self.poll()
        self._schedule_next_hour()

    def stop(self) -> None:
        self._timer.stop()

    def reschedule(self) -> None:
        '''Re-align after a system time or time-zone change.'''

        if self._timer.isActive():
            self._timer.stop()
            self.poll()
            self._schedule_next_hour()

    def poll(self) -> bool:
        '''Evaluate the current hour and return whether a chime was emitted.'''

        current = self._now()
        if current.minute != 0:
            return False

        hour_key = (current.year, current.month, current.day, current.hour)
        if hour_key == self._last_hour:
            return False
        # Consume the hour even when disabled or suppressed. Unlocking or leaving
        # full screen later in the same minute must not create a delayed chime.
        self._last_hour = hour_key

        if not self._enabled or not self._is_allowed():
            return False

        display_hour = current.hour % 12 or 12
        may_play_sound = self._sound_enabled and not self._is_quiet(current.time())
        self.chime.emit(display_hour, may_play_sound)
        return True

    def _is_allowed(self) -> bool:
        if not self._runtime_allowed:
            return False
        if self._allowed_provider is None:
            return True
        try:
            return bool(self._allowed_provider())
        except Exception:
            # Sensor failure must never produce sound or an intrusive animation.
            return False

    def _is_quiet(self, current: time) -> bool:
        start = self._quiet_start
        end = self._quiet_end
        if start == end:
            return False
        if start < end:
            return start <= current < end
        return current >= start or current < end

    def _on_timeout(self) -> None:
        self.poll()
        self._schedule_next_hour()

    def _schedule_next_hour(self) -> None:
        current = self._now()
        next_hour = (current + timedelta(hours=1)).replace(
            minute=0,
            second=0,
            microsecond=0,
        )
        delay_ms = max(1, math.ceil((next_hour - current).total_seconds() * 1000))
        self._timer.start(delay_ms)


def _parse_clock_time(value: str | time) -> time:
    if isinstance(value, time):
        return value.replace(second=0, microsecond=0, tzinfo=None)
    if not isinstance(value, str):
        raise TypeError('quiet hours must use HH:MM strings or datetime.time values')
    if re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', value) is None:
        raise ValueError('quiet hours must use strict HH:MM format')
    return time(int(value[:2]), int(value[3:]))
