"""Monotonic work/break state machine."""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Callable

from PySide6.QtCore import QObject, Qt, QTimer, Signal

log = logging.getLogger(__name__)

# Mode presets: (work_seconds, break_seconds)
_MODE_PRESETS = {
    "pomodoro": (25 * 60, 5 * 60),
    "20-20-20": (20 * 60, 20),
}
_VALID_MODES = frozenset((*_MODE_PRESETS, "custom"))


class BreakReminder(QObject):
    """Manage a work/rest cycle using one monotonic deadline.

    A repeating Qt timer is only a wake-up source; remaining time is always
    derived from ``time.monotonic()``.  Event-loop stalls and system sleep can
    therefore no longer make the countdown drift.
    """

    break_started = Signal()
    break_ended = Signal()
    tick = Signal(int, int)  # (remaining_seconds, total_seconds)
    state_changed = Signal()

    def __init__(
        self,
        parent: QObject | None = None,
        clock: Callable[[], float] | None = None,
    ):
        super().__init__(parent)
        self._clock = clock or time.monotonic

        self._work_duration = 25 * 60
        self._break_duration = 5 * 60
        self._micro_break_interval = 20 * 60
        self._micro_break_duration = 20
        self._force_break = False
        self._mode = "pomodoro"

        self._is_on_break = False
        self._enabled = False
        self._paused = False
        self._remaining = 0
        self._total = 0
        self._deadline: float | None = None

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.timeout.connect(self._on_tick)
        # v0.1.1 used this private name; keeping the alias helps external tests
        # without introducing a second timer.
        self._tick_timer = self._timer

    @property
    def work_duration(self) -> int:
        return self._work_duration

    @property
    def break_duration(self) -> int:
        return self._break_duration

    @property
    def micro_break_interval(self) -> int:
        return self._micro_break_interval

    @property
    def micro_break_duration(self) -> int:
        return self._micro_break_duration

    @property
    def force_break(self) -> bool:
        return self._force_break

    @force_break.setter
    def force_break(self, value: bool) -> None:
        self._force_break = bool(value)
        self.state_changed.emit()

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def phase(self) -> str:
        if not self._enabled:
            return "stopped"
        return "resting" if self._is_on_break else "working"

    @property
    def is_on_break(self) -> bool:
        return self._is_on_break

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def paused(self) -> bool:
        return self._paused

    @property
    def remaining(self) -> int:
        if self._enabled and not self._paused and self._deadline is not None:
            self._remaining = self._remaining_from_deadline()
        return self._remaining

    @property
    def total(self) -> int:
        return self._total

    @property
    def deadline(self) -> float | None:
        """Current monotonic deadline, mainly useful to diagnostics/tests."""
        return self._deadline

    def start(self) -> None:
        """Start (or restart) with a complete work phase."""
        self._enabled = True
        self._paused = False
        self._start_work_phase()
        log.info(
            "Break reminder started (mode=%s, work=%ds, break=%ds)",
            self._mode,
            self._work_duration,
            self._break_duration,
        )

    def stop(self) -> None:
        """Stop the state machine and clear its current deadline."""
        was_on_break = self._is_on_break
        self._timer.stop()
        self._enabled = False
        self._paused = False
        self._is_on_break = False
        self._remaining = 0
        self._total = 0
        self._deadline = None
        if was_on_break:
            self.break_ended.emit()
        self.state_changed.emit()
        log.info("Break reminder stopped")

    def pause(self) -> None:
        """Freeze the current phase at its monotonic remaining time."""
        if not self._enabled or self._paused:
            return
        self._remaining = self._remaining_from_deadline()
        self._deadline = None
        self._timer.stop()
        self._paused = True
        self.tick.emit(self._remaining, self._total)
        self.state_changed.emit()
        log.info("Break reminder paused (%ds remaining)", self._remaining)

    def resume(self) -> None:
        """Resume a paused phase without resetting it."""
        if not self._enabled or not self._paused:
            return
        self._paused = False
        self._deadline = self._clock() + max(0, self._remaining)
        self._timer.start()
        self.state_changed.emit()
        log.info("Break reminder resumed (%ds remaining)", self._remaining)

    def snooze(self, seconds: int = 5 * 60) -> None:
        """Delay the next rest phase, or dismiss an active rest temporarily."""
        if not self._enabled:
            return
        seconds = max(1, int(seconds))
        if self._is_on_break:
            self._timer.stop()
            self._is_on_break = False
            self.break_ended.emit()
            self._start_work_phase(seconds)
        elif self._paused:
            self._remaining += seconds
            self._total = max(self._total, self._remaining)
            self.tick.emit(self._remaining, self._total)
            self.state_changed.emit()
        else:
            remaining = self._remaining_from_deadline() + seconds
            self._deadline = self._clock() + remaining
            self._remaining = remaining
            self._total = max(self._total, remaining)
            self.tick.emit(self._remaining, self._total)
            self.state_changed.emit()
        log.info("Break reminder snoozed for %ds", seconds)

    def skip_break(self) -> None:
        """End the current break early and start a full work phase."""
        if not self._is_on_break:
            return
        self._timer.stop()
        self._is_on_break = False
        self._paused = False
        self.break_ended.emit()
        self._start_work_phase()
        log.info("Break skipped")

    def set_mode(self, mode: str) -> None:
        """Set ``pomodoro``, ``20-20-20`` or ``custom`` mode."""
        if mode not in _VALID_MODES:
            raise ValueError(f"Unknown break mode: {mode}")
        self._mode = mode
        if mode in _MODE_PRESETS:
            self._work_duration, self._break_duration = _MODE_PRESETS[mode]
        self.state_changed.emit()
        log.info(
            "Mode set to %s (work=%ds, break=%ds)",
            mode,
            self._work_duration,
            self._break_duration,
        )

    def set_work_duration(self, seconds: int) -> None:
        self._work_duration = max(1, int(seconds))
        self.state_changed.emit()

    def set_break_duration(self, seconds: int) -> None:
        self._break_duration = max(1, int(seconds))
        self.state_changed.emit()

    def set_micro_break_interval(self, seconds: int) -> None:
        self._micro_break_interval = max(1, int(seconds))
        self.state_changed.emit()

    def set_micro_break_duration(self, seconds: int) -> None:
        self._micro_break_duration = max(1, int(seconds))
        self.state_changed.emit()

    def _start_work_phase(self, duration: int | None = None) -> None:
        self._is_on_break = False
        self._begin_phase(duration or self._work_duration)

    def _start_break_phase(self) -> None:
        self._is_on_break = True
        self._begin_phase(self._break_duration)
        self.break_started.emit()

    def _begin_phase(self, duration: int) -> None:
        self._paused = False
        self._total = max(1, int(duration))
        self._remaining = self._total
        self._deadline = self._clock() + self._total
        self._timer.start()
        self.state_changed.emit()

    def _remaining_from_deadline(self) -> int:
        if self._deadline is None:
            return max(0, self._remaining)
        delta = self._deadline - self._clock()
        # A 1 s Qt wake-up may land a few milliseconds before the exact
        # deadline on some Windows timer backends.  Treat that tiny margin as
        # due so one-second phases do not take two ticks.
        if delta <= 0.05:
            return 0
        return max(0, int(math.ceil(delta)))

    def _on_tick(self) -> None:
        if not self._enabled or self._paused:
            return
        self._remaining = self._remaining_from_deadline()
        self.tick.emit(self._remaining, self._total)
        self.state_changed.emit()
        if self._remaining > 0:
            return

        self._timer.stop()
        if self._is_on_break:
            self._is_on_break = False
            self.break_ended.emit()
            self._start_work_phase()
        else:
            self._start_break_phase()
