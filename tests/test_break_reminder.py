"""Unit tests for BreakReminder."""

import sys
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QCoreApplication, QTimer
from PySide6.QtTest import QSignalSpy

from opencareyes.core.break_reminder import BreakReminder


@pytest.fixture(scope="session")
def qapp():
    """Ensure a QCoreApplication exists for the test session."""
    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication(sys.argv)
    return app


@pytest.fixture()
def reminder(qapp):
    """Create a fresh BreakReminder for each test."""
    r = BreakReminder()
    yield r
    r.stop()


# ---- Mode switching ----

class TestModeSwitching:
    def test_default_mode_is_pomodoro(self, reminder):
        assert reminder.mode == "pomodoro"
        assert reminder.work_duration == 25 * 60
        assert reminder.break_duration == 5 * 60

    def test_set_mode_20_20_20(self, reminder):
        reminder.set_mode("20-20-20")
        assert reminder.mode == "20-20-20"
        assert reminder.work_duration == 20 * 60
        assert reminder.break_duration == 20

    def test_set_mode_pomodoro(self, reminder):
        reminder.set_mode("20-20-20")
        reminder.set_mode("pomodoro")
        assert reminder.mode == "pomodoro"
        assert reminder.work_duration == 25 * 60
        assert reminder.break_duration == 5 * 60

    def test_set_mode_custom_keeps_durations(self, reminder):
        reminder.set_work_duration(600)
        reminder.set_break_duration(60)
        reminder.set_mode("custom")
        assert reminder.mode == "custom"
        assert reminder.work_duration == 600
        assert reminder.break_duration == 60


# ---- Duration setters ----

class TestDurationSetters:
    def test_set_work_duration(self, reminder):
        reminder.set_work_duration(1800)
        assert reminder.work_duration == 1800

    def test_set_break_duration(self, reminder):
        reminder.set_break_duration(120)
        assert reminder.break_duration == 120

    def test_set_work_duration_clamps_to_one(self, reminder):
        reminder.set_work_duration(0)
        assert reminder.work_duration == 1

    def test_set_break_duration_clamps_to_one(self, reminder):
        reminder.set_break_duration(-5)
        assert reminder.break_duration == 1


# ---- Start / Stop / Pause ----

class TestStartStopPause:
    def test_start_sets_enabled(self, reminder):
        reminder.start()
        assert reminder.enabled is True
        assert reminder.is_on_break is False

    def test_stop_clears_state(self, reminder):
        reminder.start()
        reminder.stop()
        assert reminder.enabled is False
        assert reminder.is_on_break is False
        assert reminder.remaining == 0

    def test_pause_and_resume(self, reminder):
        reminder.start()
        reminder.pause()
        assert reminder.paused is True
        reminder.resume()
        assert reminder.paused is False

    def test_pause_when_not_started_is_noop(self, reminder):
        reminder.pause()
        assert reminder.paused is False

    def test_resume_when_not_paused_is_noop(self, reminder):
        reminder.start()
        reminder.resume()  # not paused, should be noop
        assert reminder.paused is False


# ---- Signal emissions ----

class TestSignals:
    def test_tick_signal_emitted(self, reminder, qapp):
        reminder.set_work_duration(3)
        spy = QSignalSpy(reminder.tick)
        reminder.start()
        # Process events to let the timer fire once
        QTimer.singleShot(1100, qapp.quit)
        qapp.exec()
        assert spy.count() >= 1
        # First tick: remaining should be work_duration - 1
        remaining, total = spy.at(0)
        assert total == 3
        assert remaining == 2

    def test_break_started_signal(self, reminder, qapp):
        reminder.set_work_duration(1)  # 1 second work
        spy = QSignalSpy(reminder.break_started)
        reminder.start()
        QTimer.singleShot(1200, qapp.quit)
        qapp.exec()
        assert spy.count() >= 1

    def test_skip_break_emits_break_ended(self, reminder, qapp):
        reminder.set_work_duration(1)
        spy_ended = QSignalSpy(reminder.break_ended)
        reminder.start()
        # Wait for break to start
        QTimer.singleShot(1200, lambda: reminder.skip_break())
        QTimer.singleShot(1500, qapp.quit)
        qapp.exec()
        assert spy_ended.count() >= 1

    def test_force_break_property(self, reminder):
        assert reminder.force_break is True
        reminder.force_break = False
        assert reminder.force_break is False
