"""Break reminder with configurable work/break cycles."""

import logging

from PySide6.QtCore import QObject, QTimer, Signal

log = logging.getLogger(__name__)

# Mode presets: (work_seconds, break_seconds)
_MODE_PRESETS = {
    "pomodoro": (25 * 60, 5 * 60),
    "20-20-20": (20 * 60, 20),
}


class BreakReminder(QObject):
    """Manages work/break cycles using QTimer."""

    break_started = Signal()
    break_ended = Signal()
    tick = Signal(int, int)  # (remaining_seconds, total_seconds)

    def __init__(self, parent=None):
        super().__init__(parent)

        # Durations (seconds)
        self._work_duration: int = 25 * 60
        self._break_duration: int = 5 * 60
        self._micro_break_interval: int = 20 * 60
        self._micro_break_duration: int = 20
        self._force_break: bool = True
        self._mode: str = "pomodoro"

        # State
        self._is_on_break: bool = False
        self._enabled: bool = False
        self._paused: bool = False
        self._remaining: int = 0
        self._total: int = 0

        # Timers
        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(1000)
        self._tick_timer.timeout.connect(self._on_tick)

    # ---- Properties ----

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
    def force_break(self, value: bool):
        self._force_break = value

    @property
    def mode(self) -> str:
        return self._mode

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
        return self._remaining

    # ---- Public methods ----

    def start(self):
        """Start the work timer."""
        self._enabled = True
        self._paused = False
        self._is_on_break = False
        self._start_work_phase()
        log.info("Break reminder started (mode=%s, work=%ds, break=%ds)",
                 self._mode, self._work_duration, self._break_duration)

    def stop(self):
        """Stop all timers and reset state."""
        was_on_break = self._is_on_break
        self._tick_timer.stop()
        self._enabled = False
        self._paused = False
        self._is_on_break = False
        self._remaining = 0
        if was_on_break:
            self.break_ended.emit()
        log.info("Break reminder stopped")

    def pause(self):
        """Pause the current timer."""
        if not self._enabled or self._paused:
            return
        self._tick_timer.stop()
        self._paused = True
        log.info("Break reminder paused (%ds remaining)", self._remaining)

    def resume(self):
        """Resume a paused timer."""
        if not self._enabled or not self._paused:
            return
        self._paused = False
        self._tick_timer.start()
        log.info("Break reminder resumed (%ds remaining)", self._remaining)

    def skip_break(self):
        """End the current break early and start a new work phase."""
        if not self._is_on_break:
            return
        self._tick_timer.stop()
        self._is_on_break = False
        self.break_ended.emit()
        self._start_work_phase()
        log.info("Break skipped")

    def set_mode(self, mode: str):
        """Set the reminder mode: 'pomodoro', '20-20-20', or 'custom'."""
        self._mode = mode
        if mode in _MODE_PRESETS:
            self._work_duration, self._break_duration = _MODE_PRESETS[mode]
        log.info("Mode set to %s (work=%ds, break=%ds)",
                 mode, self._work_duration, self._break_duration)

    def set_work_duration(self, seconds: int):
        """Set work duration in seconds."""
        self._work_duration = max(1, seconds)

    def set_break_duration(self, seconds: int):
        """Set break duration in seconds."""
        self._break_duration = max(1, seconds)

    # ---- Internal ----

    def _start_work_phase(self):
        """Begin the work countdown."""
        self._is_on_break = False
        self._total = self._work_duration
        self._remaining = self._work_duration
        self._tick_timer.start()

    def _start_break_phase(self):
        """Begin the break countdown."""
        self._is_on_break = True
        self._total = self._break_duration
        self._remaining = self._break_duration
        self.break_started.emit()
        self._tick_timer.start()

    def _on_tick(self):
        """Called every second by the tick timer."""
        self._remaining -= 1
        self.tick.emit(self._remaining, self._total)

        if self._remaining <= 0:
            self._tick_timer.stop()
            if self._is_on_break:
                self._is_on_break = False
                self.break_ended.emit()
                self._start_work_phase()
            else:
                self._start_break_phase()
