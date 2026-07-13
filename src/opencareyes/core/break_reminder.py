"""Activity-weighted short/long break state machine."""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Callable
from datetime import datetime, timedelta

from PySide6.QtCore import QObject, Qt, QTimer, Signal

log = logging.getLogger(__name__)

# (short interval, short duration, long enabled, long interval, long duration)
_MODE_PRESETS = {
    "20-20-20": (20 * 60, 20, False, 60 * 60, 5 * 60),
    "pomodoro": (25 * 60, 5 * 60, False, 60 * 60, 5 * 60),
    "balanced": (20 * 60, 20, True, 60 * 60, 5 * 60),
}
_VALID_MODES = frozenset((*_MODE_PRESETS, "custom"))
_VALID_REMINDER_STYLES = frozenset(("fullscreen", "progressive"))


class BreakReminder(QObject):
    """Count active work with one short and one optional long cadence.

    ``QTimer`` is only a wake-up source. Active work, rest, prompt escalation,
    and snooze deadlines all use a monotonic clock, so event-loop stalls do not
    introduce drift. ``work_duration``/``break_duration`` and the legacy
    signals remain available for v0.3 integrations.
    """

    break_started = Signal()
    break_ended = Signal()
    break_due = Signal(str)  # short | long
    prompt_changed = Signal(str, str)  # (kind, none | gentle | prominent)
    tick = Signal(int, int)  # legacy/current surface: (remaining, total)
    cadence_tick = Signal(int, int)  # (short_remaining, long_remaining)
    state_changed = Signal()

    PROMPT_ESCALATION_SECONDS = 60

    def __init__(
        self,
        parent: QObject | None = None,
        clock: Callable[[], float] | None = None,
    ):
        super().__init__(parent)
        self._clock = clock or time.monotonic

        self._mode = "pomodoro"
        self._short_interval = 25 * 60
        self._short_duration = 5 * 60
        self._long_enabled = False
        self._long_interval = 60 * 60
        self._long_duration = 5 * 60
        # Historical, unused v0.1 values kept as compatibility properties.
        self._micro_break_interval = 20 * 60
        self._micro_break_duration = 20
        self._force_break = False
        self._reminder_style = "fullscreen"

        self._enabled = False
        self._paused = False
        self._suspended = False
        self._suspend_was_paused = False
        self._paused_from = "working"
        self._is_on_break = False
        self._active_break_kind = ""
        self._due_kind = ""
        self._prompt_stage = "none"
        self._prompt_started_at: float | None = None
        self._prompt_elapsed = 0.0
        self._snooze_deadline: float | None = None
        self._snoozed_until: datetime | None = None

        self._short_remaining = float(self._short_interval)
        self._long_remaining = 0.0
        self._last_active_at: float | None = None
        self._remaining = 0
        self._total = 0
        self._deadline: float | None = None

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.timeout.connect(self._on_tick)
        self._tick_timer = self._timer

    # ---- Compatibility and v0.4 state ---------------------------------

    @property
    def work_duration(self) -> int:
        return self._short_interval

    @property
    def break_duration(self) -> int:
        return self._short_duration

    @property
    def short_interval(self) -> int:
        return self._short_interval

    @property
    def short_duration(self) -> int:
        return self._short_duration

    @property
    def long_enabled(self) -> bool:
        return self._long_enabled

    @property
    def long_interval(self) -> int:
        return self._long_interval

    @property
    def long_duration(self) -> int:
        return self._long_duration

    @property
    def short_remaining(self) -> int:
        short, _long = self._estimated_cadence_remaining()
        return short

    @property
    def long_remaining(self) -> int:
        _short, long = self._estimated_cadence_remaining()
        return long

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
        changed = self._force_break != bool(value)
        self._force_break = bool(value)
        if self._force_break and self._due_kind and not self._is_on_break:
            self.start_due_break()
        elif changed:
            self.state_changed.emit()

    @property
    def reminder_style(self) -> str:
        return self._reminder_style

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def cadence_mode(self) -> str:
        return self._mode

    @property
    def phase(self) -> str:
        if not self._enabled:
            return "stopped"
        if self._is_on_break:
            return "resting"
        if self._snooze_deadline is not None or (
            self._paused and self._paused_from == "snoozed"
        ):
            return "snoozed"
        if self._due_kind:
            return "prompting"
        return "working"

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
    def suspended(self) -> bool:
        """Whether runtime policy disabled surfaces while preserving cadence."""

        return self._suspended

    @property
    def due_kind(self) -> str:
        return self._due_kind

    @property
    def current_break_kind(self) -> str:
        return self._active_break_kind or self._due_kind

    @property
    def prompt_stage(self) -> str:
        return self._prompt_stage

    @property
    def snoozed_until(self) -> datetime | None:
        return self._snoozed_until

    @property
    def remaining(self) -> int:
        if not self._enabled or self._paused:
            return self._remaining
        now = self._clock()
        if self._is_on_break or self._snooze_deadline is not None:
            return self._seconds_until(self._deadline, now)
        if self._due_kind:
            return 0
        short, _long = self._estimated_cadence_remaining(now)
        return short

    @property
    def total(self) -> int:
        return self._total

    @property
    def deadline(self) -> float | None:
        """Current monotonic deadline, mainly useful to diagnostics/tests."""

        return self._deadline

    # ---- Lifecycle ------------------------------------------------------

    def start(self) -> None:
        """Start (or restart) with complete short and long work cycles."""

        self._enabled = True
        self._paused = False
        self._suspended = False
        self._suspend_was_paused = False
        self._clear_due_state()
        self._is_on_break = False
        self._active_break_kind = ""
        self._reset_both_cycles()
        self._begin_working()
        log.info(
            "Break reminder started (mode=%s, short=%ds/%ds, long=%s)",
            self._mode,
            self._short_interval,
            self._short_duration,
            self._long_enabled,
        )

    def stop(self) -> None:
        """Stop the state machine and clear every pending surface."""

        was_on_break = self._is_on_break
        had_prompt = bool(self._due_kind or self._prompt_stage != "none")
        self._timer.stop()
        self._enabled = False
        self._paused = False
        self._suspended = False
        self._suspend_was_paused = False
        self._is_on_break = False
        self._active_break_kind = ""
        self._clear_due_state()
        self._remaining = 0
        self._total = 0
        self._deadline = None
        self._last_active_at = None
        if was_on_break:
            self.break_ended.emit()
        if had_prompt:
            self.prompt_changed.emit("", "none")
        self.state_changed.emit()
        log.info("Break reminder stopped")

    def pause(self) -> None:
        """Freeze active time, prompt escalation, snooze, or rest countdown."""

        if not self._enabled or self._paused:
            return
        now = self._clock()
        self._paused_from = self.phase
        if self._paused_from == "working":
            self._consume_active_time(now)
            self._remaining = self._display_seconds(self._short_remaining)
        elif self._paused_from in {"resting", "snoozed"}:
            self._remaining = self._seconds_until(self._deadline, now)
        elif self._paused_from == "prompting":
            self._capture_prompt_elapsed(now)
            self._remaining = 0
        self._deadline = None
        self._last_active_at = None
        self._timer.stop()
        self._paused = True
        self._emit_ticks()
        self.state_changed.emit()
        log.info("Break reminder paused (%s, %ds remaining)", self._paused_from, self._remaining)

    def suspend(self) -> None:
        """Expose a disabled runtime state without resetting active cadence."""

        if self._suspended or not self._enabled:
            return
        self._suspend_was_paused = self._paused
        self.pause()
        self._enabled = False
        self._suspended = True
        self.state_changed.emit()
        log.info("Break reminder suspended with cadence preserved")

    def resume(self) -> None:
        """Resume the exact frozen phase without resetting either cadence."""

        if not self._enabled or not self._paused:
            return
        now = self._clock()
        self._paused = False
        if self._paused_from == "working":
            self._last_active_at = now
            self._deadline = now + max(0.0, self._short_remaining)
        elif self._paused_from == "resting":
            self._deadline = now + max(0, self._remaining)
        elif self._paused_from == "snoozed":
            self._snooze_deadline = now + max(0, self._remaining)
            self._deadline = self._snooze_deadline
            self._snoozed_until = datetime.now().astimezone() + timedelta(
                seconds=max(0, self._remaining)
            )
        elif self._paused_from == "prompting":
            self._prompt_started_at = now - self._prompt_elapsed
        self._timer.start()
        self.state_changed.emit()
        log.info("Break reminder resumed (%s)", self._paused_from)

    def resume_from_suspend(self) -> None:
        """Restore the exact phase frozen by :meth:`suspend`."""

        if not self._suspended:
            return
        preserve_manual_pause = self._suspend_was_paused
        self._suspend_was_paused = False
        self._enabled = True
        self._suspended = False
        if self._paused and not preserve_manual_pause:
            self.resume()
        else:
            self.state_changed.emit()

    # ---- User actions ---------------------------------------------------

    def start_due_break(self) -> bool:
        """Start the due rest countdown after a progressive prompt."""

        if not self._enabled or not self._due_kind:
            return False
        kind = self._due_kind
        duration = self._long_duration if kind == "long" else self._short_duration
        self._clear_prompt_only()
        self._snooze_deadline = None
        self._snoozed_until = None
        self._due_kind = ""
        self._active_break_kind = kind
        self._is_on_break = True
        self._paused = False
        self._total = duration
        self._remaining = duration
        now = self._clock()
        self._deadline = now + duration
        self._last_active_at = None
        self._timer.start()
        self.prompt_changed.emit("", "none")
        self.break_started.emit()
        self.state_changed.emit()
        return True

    def start_break_now(self, kind: str = "short") -> bool:
        """Begin a user-requested rest without waiting for a cadence boundary."""

        if not self._enabled or kind not in {"short", "long"}:
            return False
        if kind == "long" and not self._long_enabled:
            kind = "short"
        if self._is_on_break:
            return True
        self._due_kind = kind
        return self.start_due_break()

    def snooze(self, seconds: int = 5 * 60) -> None:
        """Delay a due reminder without counting the delay as active work."""

        if not self._enabled:
            return
        if self._force_break:
            raise ValueError("严格休息模式下不能稍后提醒")
        seconds = max(1, int(seconds))

        kind = self._active_break_kind or self._due_kind
        if kind:
            if self._is_on_break:
                self._is_on_break = False
                self._active_break_kind = ""
                self.break_ended.emit()
            self._due_kind = kind
            self._clear_prompt_only()
            self._paused = False
            now = self._clock()
            self._snooze_deadline = now + seconds
            self._deadline = self._snooze_deadline
            self._snoozed_until = datetime.now().astimezone() + timedelta(
                seconds=seconds
            )
            self._remaining = seconds
            self._total = seconds
            self._timer.start()
            self.prompt_changed.emit(kind, "none")
        elif self._paused:
            self._short_remaining += seconds
            self._remaining = self._display_seconds(self._short_remaining)
            self._total = max(self._total, self._remaining)
        else:
            self._consume_active_time(self._clock())
            self._short_remaining += seconds
            self._remaining = self._display_seconds(self._short_remaining)
            self._total = max(self._total, self._remaining)
            now = self._clock()
            self._last_active_at = now
            self._deadline = now + self._short_remaining
        self._emit_ticks()
        self.state_changed.emit()
        log.info("Break reminder snoozed for %ds", seconds)

    def dismiss_prompt(self, seconds: int = 5 * 60) -> None:
        """Treat closing/Escape on a progressive prompt as a five-minute snooze."""

        self.snooze(seconds)

    def undo_snooze(self) -> bool:
        """Return a snoozed due break to a gentle actionable prompt."""

        if (
            not self._enabled
            or self._snooze_deadline is None
            or not self._due_kind
        ):
            return False
        self._snooze_deadline = None
        self._snoozed_until = None
        self._deadline = None
        self._remaining = 0
        self._total = 0
        self._prompt_stage = "gentle"
        self._prompt_elapsed = 0.0
        self._prompt_started_at = self._clock()
        self._timer.start()
        self.prompt_changed.emit(self._due_kind, "gentle")
        self._emit_ticks()
        self.state_changed.emit()
        return True

    def skip_break(self) -> None:
        """Skip an active, prompted, or snoozed rest and reset its cadence."""

        kind = self._active_break_kind or self._due_kind
        if not kind:
            return
        was_on_break = self._is_on_break
        if kind == "long":
            self._reset_both_cycles()
        else:
            self._short_remaining = float(self._short_interval)
        self._is_on_break = False
        self._active_break_kind = ""
        self._clear_due_state()
        if was_on_break:
            self.break_ended.emit()
        self.prompt_changed.emit("", "none")
        self._begin_working()
        log.info("%s break skipped", kind)

    def complete_natural_rest(self) -> bool:
        """Reset both activity cadences after five minutes of natural rest."""

        if not self._enabled:
            self._reset_both_cycles()
            return False
        was_on_break = self._is_on_break
        had_due = bool(self._active_break_kind or self._due_kind)
        self._is_on_break = False
        self._active_break_kind = ""
        self._clear_due_state()
        self._reset_both_cycles()
        self._total = self._short_interval
        self._remaining = self._short_interval
        if self._paused:
            self._paused_from = "working"
            self._deadline = None
            self._last_active_at = None
            self._emit_ticks()
            self.state_changed.emit()
        else:
            self._begin_working()
        if was_on_break:
            self.break_ended.emit()
        if had_due:
            self.prompt_changed.emit("", "none")
        log.info("Natural rest completed; both break cadences reset")
        return True

    # Alias for integrations that read more naturally in event handlers.
    natural_rest_completed = complete_natural_rest

    # ---- Configuration --------------------------------------------------

    def set_reminder_style(self, style: str) -> None:
        if style not in _VALID_REMINDER_STYLES:
            raise ValueError(f"未知提醒样式：{style}")
        changed = style != self._reminder_style
        self._reminder_style = style
        if style == "fullscreen" and self._due_kind and not self._is_on_break:
            self.start_due_break()
        elif changed:
            self.state_changed.emit()

    def set_mode(self, mode: str) -> None:
        """Set ``pomodoro``, ``20-20-20``, ``balanced`` or ``custom``."""

        if mode not in _VALID_MODES:
            raise ValueError(f"未知休息节奏：{mode}")
        self._mode = mode
        if mode in _MODE_PRESETS:
            (
                self._short_interval,
                self._short_duration,
                self._long_enabled,
                self._long_interval,
                self._long_duration,
            ) = _MODE_PRESETS[mode]
            if self._enabled:
                self._restart_for_configuration()
                return
        self.state_changed.emit()

    def configure_cadence(
        self,
        *,
        short_interval: int,
        short_duration: int,
        long_enabled: bool = False,
        long_interval: int = 60 * 60,
        long_duration: int = 5 * 60,
        mode: str = "custom",
    ) -> None:
        """Atomically configure a custom cadence, rejecting ambiguous cycles."""

        if mode not in _VALID_MODES:
            raise ValueError(f"未知休息节奏：{mode}")
        short_interval = max(1, int(short_interval))
        short_duration = max(1, int(short_duration))
        long_interval = max(1, int(long_interval))
        long_duration = max(1, int(long_duration))
        if long_enabled and long_interval <= short_interval:
            raise ValueError("长休息周期必须大于短休息周期")
        self._mode = mode
        self._short_interval = short_interval
        self._short_duration = short_duration
        self._long_enabled = bool(long_enabled)
        self._long_interval = long_interval
        self._long_duration = long_duration
        if self._enabled:
            self._restart_for_configuration()
            return
        self.state_changed.emit()

    def set_work_duration(self, seconds: int) -> None:
        self._short_interval = max(1, int(seconds))
        if self._enabled:
            self._restart_for_configuration()
            return
        self.state_changed.emit()

    def set_break_duration(self, seconds: int) -> None:
        self._short_duration = max(1, int(seconds))
        self.state_changed.emit()

    def set_long_enabled(self, enabled: bool) -> None:
        self._long_enabled = bool(enabled)
        if not self._long_enabled:
            self._long_remaining = 0.0
        elif self._long_remaining <= 0:
            self._long_remaining = float(self._long_interval)
        self.state_changed.emit()

    def set_long_interval(self, seconds: int) -> None:
        self._long_interval = max(1, int(seconds))
        self.state_changed.emit()

    def set_long_duration(self, seconds: int) -> None:
        self._long_duration = max(1, int(seconds))
        self.state_changed.emit()

    def set_micro_break_interval(self, seconds: int) -> None:
        self._micro_break_interval = max(1, int(seconds))
        self.state_changed.emit()

    def set_micro_break_duration(self, seconds: int) -> None:
        self._micro_break_duration = max(1, int(seconds))
        self.state_changed.emit()

    # ---- State-machine internals ---------------------------------------

    def _begin_working(self) -> None:
        self._is_on_break = False
        self._paused = False
        self._paused_from = "working"
        self._total = self._short_interval
        self._remaining = self._display_seconds(self._short_remaining)
        now = self._clock()
        self._last_active_at = now
        self._deadline = now + self._short_remaining
        self._timer.start()
        self.state_changed.emit()

    def _reset_both_cycles(self) -> None:
        self._short_remaining = float(self._short_interval)
        self._long_remaining = (
            float(self._long_interval) if self._long_enabled else 0.0
        )

    def _restart_for_configuration(self) -> None:
        was_on_break = self._is_on_break
        was_paused = self._paused
        had_due = bool(self._active_break_kind or self._due_kind)
        self._is_on_break = False
        self._active_break_kind = ""
        self._clear_due_state()
        self._reset_both_cycles()
        if was_on_break:
            self.break_ended.emit()
        if had_due:
            self.prompt_changed.emit("", "none")
        if was_paused:
            self._paused = True
            self._paused_from = "working"
            self._remaining = self._short_interval
            self._total = self._short_interval
            self._deadline = None
            self._last_active_at = None
            self._timer.stop()
            self._emit_ticks()
            self.state_changed.emit()
        else:
            self._begin_working()

    def _consume_active_time(self, now: float) -> None:
        if self._last_active_at is None:
            self._last_active_at = now
            return
        elapsed = max(0.0, now - self._last_active_at)
        self._last_active_at = now
        self._short_remaining = max(0.0, self._short_remaining - elapsed)
        if self._long_enabled:
            self._long_remaining = max(0.0, self._long_remaining - elapsed)
        self._deadline = now + self._short_remaining

    def _due_break_kind(self) -> str:
        if self._long_enabled and self._long_remaining <= 0.1:
            return "long"
        if self._short_remaining <= 0.1:
            return "short"
        return ""

    def _enter_due(self, kind: str) -> None:
        self._due_kind = kind
        self._remaining = 0
        self._total = self._long_interval if kind == "long" else self._short_interval
        self._deadline = None
        self._last_active_at = None
        self._snooze_deadline = None
        self._snoozed_until = None
        self.break_due.emit(kind)
        if self._force_break or self._reminder_style == "fullscreen":
            self.start_due_break()
            return
        self._prompt_stage = "gentle"
        self._prompt_started_at = self._clock()
        self._prompt_elapsed = 0.0
        self.prompt_changed.emit(kind, "gentle")
        self.state_changed.emit()

    def _finish_break(self) -> None:
        kind = self._active_break_kind or "short"
        self._is_on_break = False
        self._active_break_kind = ""
        if kind == "long":
            self._reset_both_cycles()
        else:
            self._short_remaining = float(self._short_interval)
        self.break_ended.emit()
        self._begin_working()

    def _resume_due_after_snooze(self) -> None:
        kind = self._due_kind
        self._snooze_deadline = None
        self._snoozed_until = None
        self._deadline = None
        if not kind:
            self._begin_working()
            return
        if self._force_break or self._reminder_style == "fullscreen":
            self.start_due_break()
            return
        self._prompt_stage = "gentle"
        self._prompt_started_at = self._clock()
        self._prompt_elapsed = 0.0
        self.prompt_changed.emit(kind, "gentle")
        self.state_changed.emit()

    def _capture_prompt_elapsed(self, now: float) -> None:
        if self._prompt_started_at is not None:
            self._prompt_elapsed = max(0.0, now - self._prompt_started_at)
        self._prompt_started_at = None

    def _update_prompt_stage(self, now: float) -> None:
        if self._prompt_started_at is None:
            self._prompt_started_at = now - self._prompt_elapsed
        elapsed = max(0.0, now - self._prompt_started_at)
        self._prompt_elapsed = elapsed
        if elapsed >= self.PROMPT_ESCALATION_SECONDS and self._prompt_stage == "gentle":
            self._prompt_stage = "prominent"
            self.prompt_changed.emit(self._due_kind, "prominent")
            self.state_changed.emit()

    def _clear_prompt_only(self) -> None:
        self._prompt_stage = "none"
        self._prompt_started_at = None
        self._prompt_elapsed = 0.0

    def _clear_due_state(self) -> None:
        self._due_kind = ""
        self._clear_prompt_only()
        self._snooze_deadline = None
        self._snoozed_until = None

    def _estimated_cadence_remaining(
        self, now: float | None = None
    ) -> tuple[int, int]:
        short = self._short_remaining
        long = self._long_remaining
        if (
            self._enabled
            and not self._paused
            and self.phase == "working"
            and self._last_active_at is not None
        ):
            elapsed = max(0.0, (self._clock() if now is None else now) - self._last_active_at)
            short = max(0.0, short - elapsed)
            if self._long_enabled:
                long = max(0.0, long - elapsed)
        return (
            self._display_seconds(short),
            self._display_seconds(long) if self._long_enabled else 0,
        )

    def _emit_ticks(self) -> None:
        short, long = self._estimated_cadence_remaining()
        self.cadence_tick.emit(short, long)
        self.tick.emit(max(0, int(self._remaining)), max(0, int(self._total)))

    @staticmethod
    def _display_seconds(value: float) -> int:
        # Windows timer wake-ups can arrive a few dozen milliseconds before a
        # displayed second boundary. Keep the label from repeating a second.
        value -= 0.1
        return 0 if value <= 0 else int(math.ceil(value))

    @classmethod
    def _seconds_until(cls, deadline: float | None, now: float) -> int:
        if deadline is None:
            return 0
        return cls._display_seconds(deadline - now)

    def _on_tick(self) -> None:
        if not self._enabled or self._paused:
            return
        now = self._clock()
        if self._is_on_break:
            self._remaining = self._seconds_until(self._deadline, now)
            self._emit_ticks()
            if self._remaining <= 0:
                self._timer.stop()
                self._finish_break()
            return

        if self._snooze_deadline is not None:
            self._remaining = self._seconds_until(self._snooze_deadline, now)
            self._emit_ticks()
            if self._remaining <= 0:
                self._resume_due_after_snooze()
            return

        if self._due_kind:
            self._remaining = 0
            self._update_prompt_stage(now)
            self._emit_ticks()
            return

        self._consume_active_time(now)
        self._remaining = self._display_seconds(self._short_remaining)
        self._total = self._short_interval
        self._emit_ticks()
        kind = self._due_break_kind()
        if kind:
            self._enter_due(kind)
