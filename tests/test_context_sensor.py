"""Fake-backend tests for queued context sensing."""

import ctypes
from datetime import datetime, timezone

from PySide6.QtTest import QSignalSpy

from opencareyes.domain.context import ContextSnapshot
from opencareyes.platform import win32_api as api
from opencareyes.platform.context_sensor import (
    ContextSensor,
    WindowsSessionEventFilter,
)


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class FakeBackend:
    def __init__(self):
        self.snapshot = ContextSnapshot(
            foreground_app_id="browser.exe",
            notification_mode="normal",
            captured_at=datetime(2026, 7, 13, tzinfo=timezone.utc),
        )
        self.error = None
        self.hook_callback = None
        self.hook_started = 0
        self.hook_stopped = 0
        self.sample_count = 0

    def sample(self, session):
        self.sample_count += 1
        if self.error is not None:
            raise self.error
        return ContextSnapshot(
            session=session,
            foreground_app_id=self.snapshot.foreground_app_id,
            fullscreen=self.snapshot.fullscreen,
            notification_mode=self.snapshot.notification_mode,
            idle_seconds=self.snapshot.idle_seconds,
            captured_at=self.snapshot.captured_at,
        )

    def start_foreground_hook(self, callback):
        self.hook_started += 1
        self.hook_callback = callback
        return True

    def stop_foreground_hook(self):
        self.hook_stopped += 1

    def emit_foreground_event(self):
        self.hook_callback()


def make_sensor(backend, clock=None):
    return ContextSensor(
        backend=backend,
        poll_interval_ms=60_000,
        stale_after_seconds=5,
        monotonic=clock or FakeClock(),
    )


def test_start_samples_immediately_and_is_idempotent(qtbot):
    backend = FakeBackend()
    sensor = make_sensor(backend)

    sensor.start()
    sensor.start()

    assert backend.hook_started == 1
    assert backend.sample_count == 1
    assert sensor.available
    assert sensor.current_snapshot.foreground_app_id == "browser.exe"
    sensor.stop()
    sensor.stop()
    assert backend.hook_stopped == 1


def test_native_hook_callback_is_delivered_through_queued_signal(qtbot):
    backend = FakeBackend()
    sensor = make_sensor(backend)
    spy = QSignalSpy(sensor.snapshot_changed)
    sensor.start()
    initial_count = backend.sample_count
    backend.snapshot = ContextSnapshot(
        foreground_app_id="powerpnt.exe",
        fullscreen=True,
        notification_mode="presentation",
        captured_at=datetime(2026, 7, 13, 1, tzinfo=timezone.utc),
    )

    backend.emit_foreground_event()

    qtbot.waitUntil(lambda: backend.sample_count > initial_count)
    assert sensor.current_snapshot.foreground_app_id == "powerpnt.exe"
    assert sensor.current_snapshot.fullscreen
    assert spy.count() >= 2
    sensor.stop()


def test_lock_and_suspend_injections_are_queued_and_suspension_wins(qtbot):
    backend = FakeBackend()
    sensor = make_sensor(backend)
    sensor.start()

    sensor.set_session_locked(True)
    qtbot.waitUntil(lambda: sensor.current_snapshot.session == "locked")
    sensor.set_system_suspended(True)
    qtbot.waitUntil(lambda: sensor.current_snapshot.session == "suspended")
    sensor.set_session_locked(False)
    qtbot.wait(1)
    assert sensor.current_snapshot.session == "suspended"
    sensor.set_system_suspended(False)
    qtbot.waitUntil(lambda: sensor.current_snapshot.session == "active")
    sensor.stop()


def test_short_probe_failure_keeps_last_snapshot_then_fails_open(qtbot):
    backend = FakeBackend()
    clock = FakeClock()
    sensor = make_sensor(backend, clock)
    availability = QSignalSpy(sensor.availability_changed)
    sensor.start()
    original = sensor.current_snapshot

    backend.error = RuntimeError("C:\\private\\window-title.txt")
    clock.now = 1
    sensor._sample_now()
    assert sensor.available
    assert sensor.current_snapshot == original

    clock.now = 6.1
    sensor._sample_now()
    assert not sensor.available
    assert sensor.current_snapshot.foreground_app_id == ""
    assert not sensor.current_snapshot.fullscreen
    assert sensor.current_snapshot.notification_mode == "unavailable"
    assert sensor.current_snapshot.idle_seconds == 0
    assert availability.at(availability.count() - 1) == [
        False,
        "context_probe_failed",
    ]
    sensor.stop()


def test_sensor_recovers_after_probe_failure(qtbot):
    backend = FakeBackend()
    clock = FakeClock()
    backend.error = RuntimeError("failed")
    sensor = make_sensor(backend, clock)
    sensor.start()
    assert not sensor.available

    backend.error = None
    backend.snapshot = ContextSnapshot(
        foreground_app_id="code.exe",
        notification_mode="normal",
    )
    clock.now = 1
    sensor._sample_now()

    assert sensor.available
    assert sensor.current_snapshot.foreground_app_id == "code.exe"
    sensor.stop()


def test_stopping_sensor_disables_timer_and_unhooks_backend():
    backend = FakeBackend()
    sensor = make_sensor(backend)
    sensor.start()

    sensor.stop()

    assert not sensor._timer.isActive()
    assert backend.hook_stopped == 1


def test_native_message_parser_covers_lock_suspend_and_resume():
    interpret = WindowsSessionEventFilter.interpret_message

    assert interpret(api.WM_WTSSESSION_CHANGE, api.WTS_SESSION_LOCK) == (
        "session_locked",
        True,
    )
    assert interpret(api.WM_WTSSESSION_CHANGE, api.WTS_SESSION_UNLOCK) == (
        "session_locked",
        False,
    )
    assert interpret(api.WM_POWERBROADCAST, api.PBT_APMSUSPEND) == (
        "system_suspended",
        True,
    )
    assert interpret(api.WM_POWERBROADCAST, api.PBT_APMRESUMEAUTOMATIC) == (
        "system_suspended",
        False,
    )
    assert interpret(0, 0) is None


def test_native_event_filter_dispatches_matching_window_via_queued_setter(qtbot):
    sensor = make_sensor(FakeBackend())
    event_filter = WindowsSessionEventFilter(sensor)
    event_filter._hwnd = 1234
    message = api.MSG()
    message.hwnd = 1234
    message.message = api.WM_WTSSESSION_CHANGE
    message.wParam = api.WTS_SESSION_LOCK

    handled = event_filter.nativeEventFilter(
        b"windows_generic_MSG",
        ctypes.addressof(message),
    )

    assert handled == (False, 0)
    qtbot.waitUntil(lambda: sensor.current_snapshot.session == "locked")
