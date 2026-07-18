"""Fake-backend tests for queued context sensing."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from PySide6.QtTest import QSignalSpy

from opencareyes.domain.context import ContextSnapshot
from opencareyes.platform import context_sensor as context_sensor_module
from opencareyes.platform.context_sensor import ContextSensor, Win32ContextBackend


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


@pytest.mark.parametrize(
    ("is_own_window", "mode", "expected_mode"),
    [
        (True, "busy", "normal"),
        (False, "busy", "busy"),
        (True, "presentation", "presentation"),
        (True, "d3d_fullscreen", "d3d_fullscreen"),
    ],
)
def test_win32_backend_ignores_only_own_window_busy(
    monkeypatch,
    is_own_window,
    mode,
    expected_mode,
):
    backend = Win32ContextBackend.__new__(Win32ContextBackend)
    backend._own_process_id = 42
    process_id = 42 if is_own_window else 99
    monkeypatch.setattr(
        context_sensor_module,
        "api",
        SimpleNamespace(GetForegroundWindow=lambda: 123),
    )
    monkeypatch.setattr(backend, "_window_process_id", lambda _hwnd: process_id)
    monkeypatch.setattr(backend, "_window_class", lambda _hwnd: "")
    monkeypatch.setattr(backend, "_application_id", lambda _pid: "external.exe")
    monkeypatch.setattr(backend, "_is_fullscreen", lambda _hwnd: False)
    monkeypatch.setattr(backend, "_notification_mode", lambda: mode)
    monkeypatch.setattr(backend, "_idle_seconds", lambda: 0)

    snapshot = backend.sample("active")

    assert snapshot.notification_mode == expected_mode
    assert snapshot.foreground_app_id == ("" if is_own_window else "external.exe")
    assert snapshot.fullscreen is False


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
