"""Integration tests for context debounce and temporary effect suppression."""

from __future__ import annotations

import time
from types import SimpleNamespace

from PySide6.QtCore import QObject, Signal

from opencareyes.application.context_coordinator import ContextCoordinator
from opencareyes.application.effect_coordinator import EffectCoordinator
from opencareyes.domain.context import (
    ContextSnapshot,
    FeatureSuppression,
    SuppressionDecision,
)


class FakeToggle:
    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self.enable_count = 0
        self.fail_enable_count = 0
        self.fail_disable_count = 0

    def enable(self, *_args):
        self.enable_count += 1
        if self.fail_enable_count:
            self.fail_enable_count -= 1
            return False
        self.enabled = True
        return True

    def disable(self):
        if self.fail_disable_count:
            self.fail_disable_count -= 1
            raise RuntimeError("disable failed")
        self.enabled = False
        return True


class FakeBreakReminder:
    def __init__(self):
        self.enabled = True
        self.paused = False
        self.start_count = 0

    def start(self):
        self.enabled = True
        self.paused = False
        self.start_count += 1

    def stop(self):
        self.enabled = False
        self.paused = False

    def pause(self):
        if self.enabled:
            self.paused = True

    def resume(self):
        if self.enabled:
            self.paused = False


class FakeSensor(QObject):
    snapshot_changed = Signal(object)
    availability_changed = Signal(bool, str)

    def __init__(self):
        super().__init__()
        self.current_snapshot = ContextSnapshot(notification_mode="normal")
        self.started = False

    def publish(self, snapshot: ContextSnapshot) -> None:
        self.current_snapshot = snapshot
        self.snapshot_changed.emit(snapshot)

    def start(self):
        self.started = True

    def stop(self):
        self.started = False


class StartupFullscreenSensor(FakeSensor):
    def start(self):
        super().start()
        self.publish(
            ContextSnapshot(
                foreground_app_id="player.exe",
                fullscreen=True,
                notification_mode="normal",
            )
        )


def _settings(**overrides):
    values = {
        "smart_pause_enabled": True,
        "fullscreen_pause_enabled": True,
        "natural_rest_enabled": True,
        "app_rules": (),
        "filter_enabled": True,
        "color_temperature": 4200,
        "dimmer_enabled": True,
        "dim_level": 80,
        "break_enabled": True,
        "focus_enabled": True,
        "global_pause_mode": "none",
        "global_pause_until": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _runtime(settings=None):
    settings = settings or _settings()
    sensor = FakeSensor()
    reminder = FakeBreakReminder()
    effects = EffectCoordinator(
        settings,
        blue_filter=FakeToggle(),
        dimmer=FakeToggle(),
        break_reminder=reminder,
        focus_mode=FakeToggle(),
    )
    coordinator = ContextCoordinator(settings, sensor, effects)
    return coordinator, sensor, effects, reminder


def test_initial_fullscreen_sample_never_flashes_focus_overlay():
    settings = _settings(
        filter_enabled=False,
        dimmer_enabled=False,
        break_enabled=False,
        focus_enabled=True,
    )
    sensor = StartupFullscreenSensor()
    focus = FakeToggle(enabled=False)
    effects = EffectCoordinator(settings, focus_mode=focus)
    coordinator = ContextCoordinator(settings, sensor, effects)

    coordinator.start()

    assert focus.enable_count == 0
    assert focus.enabled is False
    assert effects.state.focus.suppressed_by == ("fullscreen",)
    coordinator.stop()


def test_repeated_one_hz_snapshot_does_not_restart_debounce(qtbot):
    coordinator, sensor, _effects, reminder = _runtime()
    fullscreen = ContextSnapshot(
        foreground_app_id="player.exe",
        fullscreen=True,
        notification_mode="normal",
    )

    sensor.publish(fullscreen)
    qtbot.wait(300)
    sensor.publish(fullscreen)
    qtbot.wait(300)
    assert reminder.paused is True

    normal = ContextSnapshot(
        foreground_app_id="player.exe",
        notification_mode="normal",
    )
    sensor.publish(normal)
    qtbot.wait(1100)
    sensor.publish(normal)
    qtbot.wait(1050)
    assert reminder.paused is False
    coordinator.stop()


def test_presentation_and_d3d_suppress_immediately(qtbot):
    coordinator, sensor, effects, reminder = _runtime()

    sensor.publish(ContextSnapshot(
        foreground_app_id="powerpnt.exe",
        notification_mode="presentation",
    ))

    qtbot.waitUntil(lambda: reminder.paused, timeout=200)
    assert effects.state.breaks.suppressed_by == ("presentation",)
    assert effects.state.focus.suppressed_by == ("presentation",)
    coordinator.stop()


def test_manual_override_expires_at_natural_rest_boundary(qtbot):
    settings = _settings()
    coordinator, sensor, effects, reminder = _runtime(settings)

    sensor.publish(ContextSnapshot(
        foreground_app_id="editor.exe",
        notification_mode="normal",
        idle_seconds=180,
    ))
    qtbot.waitUntil(lambda: reminder.paused, timeout=800)
    assert coordinator.resume_breaks_for_current_context() is True
    assert reminder.paused is False
    assert settings.break_enabled is True

    sensor.publish(ContextSnapshot(
        foreground_app_id="editor.exe",
        notification_mode="normal",
        idle_seconds=301,
    ))
    qtbot.waitUntil(lambda: reminder.paused, timeout=800)
    assert effects.state.breaks.suppressed_by == ("idle",)

    sensor.publish(ContextSnapshot(
        foreground_app_id="editor.exe",
        notification_mode="normal",
        idle_seconds=0,
    ))
    qtbot.waitUntil(lambda: not reminder.paused, timeout=2500)
    assert reminder.start_count == 1
    coordinator.stop()


def test_idle_freezes_break_cadence_when_smart_pause_is_disabled(qtbot):
    settings = _settings(
        smart_pause_enabled=False,
        natural_rest_enabled=False,
    )
    coordinator, sensor, effects, reminder = _runtime(settings)

    sensor.publish(
        ContextSnapshot(notification_mode="normal", idle_seconds=180)
    )
    qtbot.waitUntil(lambda: reminder.paused, timeout=800)

    assert effects.state.breaks.suppressed_by == ("idle",)
    assert not effects.state.focus.suppressed_by

    sensor.publish(
        ContextSnapshot(notification_mode="normal", idle_seconds=0)
    )
    qtbot.waitUntil(lambda: not reminder.paused, timeout=2500)
    coordinator.stop()


def test_failed_transition_keeps_old_decision_and_retries():
    settings = _settings(break_enabled=False, focus_enabled=False)
    blue_filter = FakeToggle()
    dimmer = FakeToggle()
    dimmer.fail_disable_count = 1
    effects = EffectCoordinator(
        settings,
        blue_filter=blue_filter,
        dimmer=dimmer,
    )
    failures = []
    effects.operation_failed.connect(lambda code, message: failures.append((code, message)))
    decision = SuppressionDecision(
        filter=FeatureSuppression(("app:game.exe",), "leave_application"),
        dimmer=FeatureSuppression(("app:game.exe",), "leave_application"),
    )

    effects.apply(decision)

    assert effects.last_apply_succeeded is False
    assert effects.state.filter.suppressed_by == ()
    assert blue_filter.enabled is True
    assert dimmer.enabled is True
    assert failures[0][0] == "context_effect"
    assert failures[0][1] == "屏幕调暗未能应用，请重试。"
    assert "disable failed" not in failures[0][1]

    effects.apply(decision)
    assert effects.last_apply_succeeded is True
    assert effects.state.filter.suppressed_by == ("app_rule",)
    assert blue_filter.enabled is False
    assert dimmer.enabled is False


def test_context_failure_signal_does_not_expose_service_detail():
    settings = _settings(break_enabled=False, focus_enabled=False)
    dimmer = FakeToggle()
    dimmer.fail_disable_count = 1
    effects = EffectCoordinator(
        settings,
        blue_filter=FakeToggle(),
        dimmer=dimmer,
    )
    coordinator = ContextCoordinator(settings, FakeSensor(), effects)
    failures = []
    coordinator.operation_failed.connect(
        lambda code, message: failures.append((code, message))
    )
    decision = SuppressionDecision(
        filter=FeatureSuppression(("app:game.exe",), "leave_application"),
        dimmer=FeatureSuppression(("app:game.exe",), "leave_application"),
    )

    coordinator._apply(
        ContextSnapshot(foreground_app_id="game.exe"),
        decision,
        report_failure=True,
    )

    assert failures == [
        ("context_effect", "情境切换效果未能应用，请重试。")
    ]
    assert "disable failed" not in failures[0][1]


def test_compensation_failure_is_reported_and_visible_in_state():
    settings = _settings(break_enabled=False, focus_enabled=False)
    blue_filter = FakeToggle()
    blue_filter.fail_enable_count = 1
    dimmer = FakeToggle()
    dimmer.fail_disable_count = 1
    effects = EffectCoordinator(
        settings,
        blue_filter=blue_filter,
        dimmer=dimmer,
    )
    failures = []
    effects.operation_failed.connect(lambda code, message: failures.append((code, message)))
    decision = SuppressionDecision(
        filter=FeatureSuppression(("app:game.exe",), "leave_application"),
        dimmer=FeatureSuppression(("app:game.exe",), "leave_application"),
    )

    effects.apply(decision)

    assert any(code == "context_compensation" for code, _message in failures)
    assert all("disable failed" not in message for _code, message in failures)
    assert any(
        message == "效果回滚不完整，请重启 OpenCareEyes 后检查设置。"
        for code, message in failures
        if code == "context_compensation"
    )
    assert effects.state.filter.effective_enabled is False
    assert effects.state.filter.suppressed_by == ()


def test_expired_timed_global_pause_does_not_block_context_effects():
    settings = _settings(
        break_enabled=False,
        focus_enabled=False,
        global_pause_mode="timed",
        global_pause_until=time.time() - 1,
    )
    blue_filter = FakeToggle()
    effects = EffectCoordinator(settings, blue_filter=blue_filter, dimmer=FakeToggle())

    effects.apply(SuppressionDecision(
        filter=FeatureSuppression(("app:game.exe",), "leave_application")
    ))

    assert blue_filter.enabled is False
    assert effects.state.filter.suppressed_by == ("app_rule",)
