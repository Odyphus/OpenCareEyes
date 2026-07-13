"""v0.4 activity cadence and progressive reminder tests."""

import pytest
from PySide6.QtTest import QSignalSpy

from opencareyes.core.break_reminder import BreakReminder


class _Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _custom(clock: _Clock, *, progressive: bool = True) -> BreakReminder:
    reminder = BreakReminder(clock=clock)
    reminder.configure_cadence(
        short_interval=2,
        short_duration=1,
        long_enabled=True,
        long_interval=5,
        long_duration=2,
    )
    reminder.set_reminder_style("progressive" if progressive else "fullscreen")
    reminder.start()
    return reminder


def test_balanced_preset_has_short_and_long_cadences() -> None:
    reminder = BreakReminder()
    reminder.set_mode("balanced")

    assert reminder.short_interval == 20 * 60
    assert reminder.short_duration == 20
    assert reminder.long_enabled is True
    assert reminder.long_interval == 60 * 60
    assert reminder.long_duration == 5 * 60


def test_long_break_wins_when_both_cadences_are_due() -> None:
    clock = _Clock()
    reminder = BreakReminder(clock=clock)
    reminder.configure_cadence(
        short_interval=2,
        short_duration=1,
        long_enabled=True,
        long_interval=3,
        long_duration=2,
    )
    reminder.set_reminder_style("progressive")
    reminder.start()

    clock.advance(3)
    reminder._on_tick()

    assert reminder.phase == "prompting"
    assert reminder.due_kind == "long"


def test_progressive_prompt_escalates_and_rest_starts_only_on_accept() -> None:
    clock = _Clock()
    reminder = _custom(clock)
    started = QSignalSpy(reminder.break_started)

    clock.advance(2)
    reminder._on_tick()
    assert reminder.phase == "prompting"
    assert reminder.prompt_stage == "gentle"
    assert started.count() == 0

    clock.advance(60)
    reminder._on_tick()
    assert reminder.prompt_stage == "prominent"
    assert started.count() == 0

    assert reminder.start_due_break() is True
    assert reminder.phase == "resting"
    assert reminder.current_break_kind == "short"
    assert started.count() == 1


def test_snooze_delay_is_not_counted_as_active_time() -> None:
    clock = _Clock()
    reminder = _custom(clock)

    clock.advance(2)
    reminder._on_tick()
    assert reminder.long_remaining == 3

    reminder.snooze(10)
    clock.advance(10)
    reminder._on_tick()

    assert reminder.phase == "prompting"
    assert reminder.long_remaining == 3


def test_short_completion_resets_only_short_cycle() -> None:
    clock = _Clock()
    reminder = _custom(clock, progressive=False)

    clock.advance(2)
    reminder._on_tick()
    assert reminder.phase == "resting"
    assert reminder.current_break_kind == "short"

    clock.advance(1)
    reminder._on_tick()

    assert reminder.phase == "working"
    assert reminder.short_remaining == 2
    assert reminder.long_remaining == 3


def test_skip_and_natural_rest_reset_the_expected_cycles() -> None:
    clock = _Clock()
    reminder = _custom(clock)
    clock.advance(2)
    reminder._on_tick()

    reminder.skip_break()
    assert reminder.short_remaining == 2
    assert reminder.long_remaining == 3

    assert reminder.complete_natural_rest() is True
    assert reminder.short_remaining == 2
    assert reminder.long_remaining == 5


def test_pause_freezes_both_activity_cadences() -> None:
    clock = _Clock()
    reminder = _custom(clock)
    clock.advance(1)
    reminder._on_tick()
    reminder.pause()
    before = (reminder.short_remaining, reminder.long_remaining)

    clock.advance(30)
    reminder._on_tick()

    assert (reminder.short_remaining, reminder.long_remaining) == before


def test_strict_mode_bypasses_progressive_prompt() -> None:
    clock = _Clock()
    reminder = _custom(clock)
    reminder.force_break = True

    clock.advance(2)
    reminder._on_tick()

    assert reminder.phase == "resting"
    assert reminder.prompt_stage == "none"


def test_custom_long_period_must_exceed_short_period() -> None:
    reminder = BreakReminder()

    with pytest.raises(ValueError, match="长休息周期"):
        reminder.configure_cadence(
            short_interval=20 * 60,
            short_duration=20,
            long_enabled=True,
            long_interval=20 * 60,
            long_duration=5 * 60,
        )


def test_changing_preset_restarts_enabled_cadence_with_new_values() -> None:
    clock = _Clock()
    reminder = _custom(clock)
    clock.advance(1)
    reminder._on_tick()

    reminder.set_mode("20-20-20")

    assert reminder.phase == "working"
    assert reminder.short_remaining == 20 * 60
    assert reminder.long_enabled is False


def test_runtime_suspend_preserves_cadence_while_reporting_disabled() -> None:
    clock = _Clock()
    reminder = _custom(clock)
    clock.advance(1)
    reminder._on_tick()
    before = (reminder.short_remaining, reminder.long_remaining)

    reminder.suspend()
    clock.advance(30)
    reminder._on_tick()

    assert reminder.enabled is False
    assert reminder.suspended is True
    assert (reminder.short_remaining, reminder.long_remaining) == before

    reminder.resume_from_suspend()

    assert reminder.enabled is True
    assert reminder.suspended is False
    assert reminder.paused is False
    assert (reminder.short_remaining, reminder.long_remaining) == before


def test_runtime_suspend_does_not_cancel_existing_manual_pause() -> None:
    clock = _Clock()
    reminder = _custom(clock)
    clock.advance(1)
    reminder._on_tick()
    reminder.pause()
    before = (reminder.short_remaining, reminder.long_remaining)

    reminder.suspend()
    reminder.resume_from_suspend()

    assert reminder.enabled is True
    assert reminder.suspended is False
    assert reminder.paused is True
    assert not reminder._timer.isActive()
    assert (reminder.short_remaining, reminder.long_remaining) == before

    reminder.resume()
    assert reminder.paused is False


def test_snooze_can_be_undone_back_to_progressive_prompt() -> None:
    clock = _Clock()
    reminder = _custom(clock)
    clock.advance(2)
    reminder._on_tick()
    reminder.snooze(300)

    assert reminder.phase == "snoozed"
    assert reminder.undo_snooze() is True
    assert reminder.phase == "prompting"
    assert reminder.prompt_stage == "gentle"
    assert reminder.remaining == 0
