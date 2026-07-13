"""Regression tests for the v0.4 runtime intent boundary."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from PySide6.QtCore import QObject, Signal
from PySide6.QtTest import QSignalSpy

from opencareyes.application.context_coordinator import ContextCoordinator
from opencareyes.application.effect_coordinator import EffectCoordinator
from opencareyes.application.state_projector import StateProjector
from opencareyes.core.break_reminder import BreakReminder
from opencareyes.domain.context import AutoPausePreferences, ContextSnapshot
from opencareyes.domain.policy import AutoPausePolicy


class Toggle:
    def __init__(self, enabled: bool = False):
        self.enabled = enabled
        self.level = None

    def enable(self, level=None):
        self.enabled = True
        self.level = level
        return True

    def disable(self):
        self.enabled = False
        return True

    def set_temperature(self, value):
        self.level = value
        return True

    def set_brightness(self, value):
        self.level = value
        return True


class PendingToggle(Toggle):
    def __init__(self):
        super().__init__()
        self.commands = []

    @property
    def pending(self):
        return bool(self.commands)

    @property
    def pending_target(self):
        for _name, target, _value in reversed(self.commands):
            if target is not None:
                return target
        return None

    def enable(self, level=None):
        self.commands.append(("enable", True, level))
        return True

    def disable(self):
        self.commands.append(("disable", False, None))
        return True

    def set_temperature(self, value):
        self.commands.append(("temperature", None, value))
        return True

    def complete_next(self):
        _name, target, value = self.commands.pop(0)
        if target is not None:
            self.enabled = target
        if value is not None:
            self.level = value


class Sensor(QObject):
    snapshot_changed = Signal(object)
    availability_changed = Signal(bool, str)

    def __init__(self):
        super().__init__()
        self.current_snapshot = ContextSnapshot(notification_mode="normal")

    def start(self):
        return None

    def stop(self):
        return None

    def publish(self, snapshot):
        self.current_snapshot = snapshot
        self.snapshot_changed.emit(snapshot)


def settings(**overrides):
    values = {
        "smart_pause_enabled": True,
        "fullscreen_pause_enabled": True,
        "natural_rest_enabled": True,
        "app_rules": (),
        "filter_enabled": True,
        "color_temperature": 4200,
        "dimmer_enabled": False,
        "dim_level": 0,
        "break_enabled": False,
        "focus_enabled": False,
        "focus_dim_level": 150,
        "global_pause_mode": "none",
        "global_pause_until": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_same_suppression_reconciles_latest_preference_and_profile(qtbot):
    preferences = settings(
        app_rules=(
            {
                "app_id": "game.exe",
                "filter": True,
                "dimmer": False,
                "breaks": False,
                "focus": False,
            },
        )
    )
    sensor = Sensor()
    blue_filter = Toggle()
    effects = EffectCoordinator(preferences, blue_filter=blue_filter)
    coordinator = ContextCoordinator(preferences, sensor, effects)
    coordinator.start()
    assert blue_filter.enabled

    sensor.publish(
        ContextSnapshot(
            foreground_app_id="game.exe",
            notification_mode="normal",
        )
    )
    qtbot.waitUntil(lambda: not blue_filter.enabled, timeout=800)

    preferences.filter_enabled = False
    coordinator.recompute()
    assert effects.state.filter.desired_enabled is False
    preferences.filter_enabled = True
    preferences.color_temperature = 3400
    coordinator.recompute()
    assert effects.state.filter.desired_enabled is True
    assert effects.state.filter.suppressed_by == ("app_rule",)
    assert not blue_filter.enabled

    sensor.publish(
        ContextSnapshot(
            foreground_app_id="editor.exe",
            notification_mode="normal",
        )
    )
    qtbot.waitUntil(lambda: blue_filter.enabled, timeout=2500)
    assert blue_filter.level == 3400
    coordinator.stop()


def test_stable_context_does_not_publish_full_runtime_each_second(qtbot):
    preferences = settings(filter_enabled=False)
    sensor = Sensor()
    effects = EffectCoordinator(preferences)
    coordinator = ContextCoordinator(preferences, sensor, effects)
    spy = QSignalSpy(coordinator.runtime_changed)
    coordinator.start()
    initial_count = spy.count()

    for second in range(1, 5):
        sensor.publish(
            ContextSnapshot(
                foreground_app_id="editor.exe",
                notification_mode="normal",
                idle_seconds=second,
                captured_at=datetime(
                    2026, 7, 13, 12, 0, second, tzinfo=timezone.utc
                ),
            )
        )
    qtbot.wait(10)

    # The first foreground-app semantic change is published; timestamp and
    # sub-threshold idle changes after it are deliberately tick-only data.
    assert spy.count() == initial_count + 1
    coordinator.stop()


def test_hdr_is_runtime_suppression_not_failed_user_preference():
    preferences = settings()
    blue_filter = Toggle()
    blue_filter.hdr_active = True
    effects = EffectCoordinator(preferences, blue_filter=blue_filter)

    result = effects.reconcile(effects.intent_from_settings())

    assert result.succeeded
    assert preferences.filter_enabled is True
    assert not blue_filter.enabled
    assert result.policy.filter.desired_enabled is True
    assert result.policy.filter.suppressed_by == ("hdr_active",)


def test_display_health_does_not_expose_backend_error_detail():
    service = SimpleNamespace(
        hdr_active=False,
        pending=False,
        capability_verified=True,
        last_error_code="private_backend_code",
        last_error_message=(
            r"native failure at C:\Users\Alice\Private\display-state.bin"
        ),
    )

    health = StateProjector(SimpleNamespace(), blue_filter=service)._display_health()

    assert health.status == "error"
    assert health.reason_code == "private_backend_code"
    assert health.message == "色温效果未能安全应用，请重试或恢复原始显示。"
    assert "native failure" not in health.message
    assert "C:\\Users" not in health.message


def test_async_display_acceptance_is_pending_until_verified():
    preferences = settings()
    blue_filter = PendingToggle()
    effects = EffectCoordinator(preferences, blue_filter=blue_filter)

    accepted = effects.reconcile(effects.intent_from_settings())

    assert accepted.succeeded
    assert blue_filter.pending
    assert accepted.policy.filter.desired_enabled is True
    assert accepted.policy.filter.effective_enabled is False

    blue_filter.complete_next()
    verified = effects.refresh()
    assert verified.filter.effective_enabled is True


def test_break_suppression_preserves_cadence_and_resumes(qtbot):
    preferences = settings(filter_enabled=False, break_enabled=True)
    reminder = BreakReminder()
    reminder.configure_cadence(
        mode="custom",
        short_interval=120,
        short_duration=20,
    )
    effects = EffectCoordinator(preferences, break_reminder=reminder)
    effects.reconcile(effects.intent_from_settings())
    remaining = reminder.short_remaining

    effects.reconcile(effects.intent_from_settings(global_pause=True))

    assert reminder.suspended is True
    assert reminder.enabled is False
    assert reminder.short_remaining == remaining

    effects.reconcile(effects.intent_from_settings(global_pause=False))
    assert reminder.suspended is False
    assert reminder.enabled is True
    assert reminder.short_remaining == remaining
    reminder.stop()


def test_idle_freeze_and_natural_reset_do_not_depend_on_smart_pause():
    now = [100.0]
    preferences = settings(
        filter_enabled=False,
        break_enabled=True,
        smart_pause_enabled=False,
    )
    reminder = BreakReminder(clock=lambda: now[0])
    reminder.configure_cadence(
        short_interval=120,
        short_duration=20,
        long_enabled=True,
        long_interval=300,
        long_duration=60,
    )
    effects = EffectCoordinator(preferences, break_reminder=reminder)
    effects.reconcile(effects.intent_from_settings())
    now[0] += 60
    reminder._on_tick()

    idle = AutoPausePolicy.evaluate(
        ContextSnapshot(idle_seconds=180, notification_mode="normal"),
        AutoPausePreferences(
            smart_pause_enabled=False,
            natural_rest_enabled=True,
        ),
        (),
    )
    effects.reconcile(
        effects.intent_from_settings(suppression=idle)
    )
    frozen = (reminder.short_remaining, reminder.long_remaining)
    now[0] += 180
    reminder._on_tick()
    assert reminder.suspended is True
    assert (reminder.short_remaining, reminder.long_remaining) == frozen

    natural = AutoPausePolicy.evaluate(
        ContextSnapshot(idle_seconds=301, notification_mode="normal"),
        AutoPausePreferences(
            smart_pause_enabled=False,
            natural_rest_enabled=True,
        ),
        (),
    )
    effects.reconcile(
        effects.intent_from_settings(suppression=natural)
    )
    active = AutoPausePolicy.evaluate(
        ContextSnapshot(idle_seconds=0, notification_mode="normal"),
        AutoPausePreferences(
            smart_pause_enabled=False,
            natural_rest_enabled=True,
        ),
        (),
    )
    effects.reconcile(effects.intent_from_settings(suppression=active))

    assert reminder.suspended is False
    assert reminder.short_remaining == 120
    assert reminder.long_remaining == 300
    reminder.stop()


def test_effect_reconcile_preserves_manual_break_pause_after_global_pause(qtbot):
    preferences = settings(filter_enabled=False, break_enabled=True)
    reminder = BreakReminder()
    effects = EffectCoordinator(preferences, break_reminder=reminder)
    effects.reconcile(effects.intent_from_settings())
    reminder.pause()
    assert reminder.paused is True

    effects.reconcile(effects.intent_from_settings(global_pause=True))
    effects.reconcile(effects.intent_from_settings(global_pause=False))

    assert reminder.enabled is True
    assert reminder.suspended is False
    assert reminder.paused is True
    assert effects.state.breaks.effective_enabled is False
    reminder.stop()
