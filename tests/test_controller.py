"""Tests for immutable state and controller-only feature writes."""

from dataclasses import FrozenInstanceError
import sys

import pytest
from PySide6.QtCore import QCoreApplication, QObject, Signal
from PySide6.QtTest import QSignalSpy

from opencareyes.config.settings import Settings
from opencareyes.controller import AppController
from opencareyes.core.break_reminder import BreakReminder


@pytest.fixture(scope="module")
def qapp():
    return QCoreApplication.instance() or QCoreApplication(sys.argv)


class MemoryStore:
    def __init__(self):
        self.values = {}

    def value(self, key, default=None, type=None):
        value = self.values.get(key, default)
        if type is not None and value is not None:
            return type(value)
        return value

    def setValue(self, key, value):
        self.values[key] = value

    def allKeys(self):
        return list(self.values)

    def sync(self):
        pass

    def clear(self):
        self.values.clear()


class FakeDisplayEffect:
    def __init__(self):
        self.enabled = False
        self.level = None
        self.fail_enable = False

    def enable(self, level=None):
        if self.fail_enable:
            raise RuntimeError("device rejected operation")
        self.enabled = True
        self.level = level

    def disable(self):
        self.enabled = False

    def set_temperature(self, value):
        self.level = value

    def set_brightness(self, value):
        self.level = value


class FakeFocus(FakeDisplayEffect):
    def set_dim_level(self, value):
        self.level = value


class FakeScheduler(QObject):
    next_event_changed = Signal(object)
    running_changed = Signal(bool)
    manual_override_changed = Signal(bool)
    error = Signal(str, str)

    def __init__(self):
        super().__init__()
        self.running = False
        self.next_event = None
        self.next_event_at = None
        self.manual_override = False
        self.callback = None

    def set_state_callback(self, callback):
        self.callback = callback

    def start(self):
        self.running = True
        self.running_changed.emit(True)

    def stop(self):
        self.running = False
        self.running_changed.emit(False)

    def reschedule(self):
        pass

    def set_manual_override(self, value):
        self.manual_override = value
        self.manual_override_changed.emit(value)


@pytest.fixture
def controller(qapp):
    settings = Settings(MemoryStore())
    blue_filter = FakeDisplayEffect()
    dimmer = FakeDisplayEffect()
    reminder = BreakReminder()
    focus = FakeFocus()
    scheduler = FakeScheduler()
    instance = AppController(
        settings,
        blue_filter,
        dimmer,
        reminder,
        focus,
        scheduler,
    )
    yield instance, settings, blue_filter, dimmer, reminder, focus, scheduler
    reminder.stop()


def test_app_state_is_immutable(controller):
    instance, *_ = controller
    with pytest.raises(FrozenInstanceError):
        instance.state.display.filter_enabled = True


def test_controller_updates_service_settings_and_snapshot(controller):
    instance, settings, blue_filter, *_ = controller
    spy = QSignalSpy(instance.state_changed)

    assert instance.set_filter_enabled(True) is True

    assert blue_filter.enabled is True
    assert settings.filter_enabled is True
    assert instance.state.display.filter_enabled is True
    assert spy.count() == 1


def test_failed_service_write_is_visible_and_not_persisted(controller):
    instance, settings, blue_filter, *_ = controller
    blue_filter.fail_enable = True
    spy = QSignalSpy(instance.operation_failed)
    state_spy = QSignalSpy(instance.state_changed)

    assert instance.set_filter_enabled(True) is False

    assert settings.filter_enabled is False
    assert instance.state.display.filter_enabled is False
    assert spy.count() == 1
    assert spy.at(0)[0] == "filter_toggle"
    assert state_spy.count() == 1
    assert state_spy.at(0)[0].display.filter_enabled is False


def test_restore_failure_rolls_back_persisted_enabled_state(qapp):
    settings = Settings(MemoryStore())
    settings.filter_enabled = True
    blue_filter = FakeDisplayEffect()
    blue_filter.fail_enable = True
    instance = AppController(settings, blue_filter=blue_filter)
    failure_spy = QSignalSpy(instance.operation_failed)
    state_spy = QSignalSpy(instance.state_changed)

    assert instance.state.display.filter_enabled is True
    assert instance.restore() is False

    assert blue_filter.enabled is False
    assert settings.filter_enabled is False
    assert instance.state.display.filter_enabled is False
    assert failure_spy.count() == 1
    assert failure_spy.at(0)[0] == "restore_filter"
    assert state_spy.count() == 1
    assert state_spy.at(0)[0].display.filter_enabled is False


def test_global_pause_preserves_preferences_and_restores_services(controller):
    instance, settings, blue_filter, dimmer, reminder, *_ = controller
    settings.filter_enabled = True
    settings.dimmer_enabled = True
    settings.break_enabled = True
    assert instance.restore() is True
    assert blue_filter.enabled and dimmer.enabled and reminder.enabled

    assert instance.pause_all() is True
    assert instance.state.global_pause.active is True
    assert settings.filter_enabled and settings.dimmer_enabled and settings.break_enabled
    assert not blue_filter.enabled and not dimmer.enabled and not reminder.enabled

    assert instance.resume_all() is True
    assert instance.state.global_pause.active is False
    assert blue_filter.enabled and dimmer.enabled and reminder.enabled


def test_schedule_boundary_applies_profiles_without_recreating_manual_override(
    controller,
):
    instance, settings, blue_filter, dimmer, *_, scheduler = controller
    scheduler.running = True

    assert instance.apply_display_profile("reading") is True
    assert scheduler.manual_override is True

    scheduler.set_manual_override(False)
    scheduler.callback(True)
    assert settings.current_preset == "night"
    assert settings.color_temperature == 3400
    assert settings.dim_level == 50
    assert blue_filter.enabled is True
    assert blue_filter.level == 3400
    assert dimmer.enabled is True
    assert dimmer.level == 50
    assert scheduler.manual_override is False

    scheduler.callback(False)
    assert settings.current_preset == "office"
    assert settings.color_temperature == 5500
    assert settings.dim_level == 0
    assert blue_filter.enabled is True
    assert blue_filter.level == 5500
    assert dimmer.enabled is False
    assert scheduler.manual_override is False


def test_fixed_schedule_event_labels_match_applied_profiles():
    from opencareyes.ui.widgets import schedule_event_description

    assert schedule_event_description("on") == "切换到夜间方案"
    assert schedule_event_description("off") == "切换到日间方案"


def test_onboarding_completion_is_published(controller):
    instance, settings, *_ = controller
    assert instance.state.general.onboarding_completed is False
    assert instance.complete_onboarding() is True
    assert settings.onboarding_completed is True
    assert instance.state.general.onboarding_completed is True


def test_break_countdown_display_is_published(controller):
    instance, settings, *_ = controller

    assert instance.set_break_countdown_display("floating") is True

    assert settings.break_countdown_display == "floating"
    assert instance.state.breaks.countdown_display == "floating"


def test_invalid_break_countdown_display_is_rejected(controller):
    instance, settings, *_ = controller
    spy = QSignalSpy(instance.operation_failed)

    assert instance.set_break_countdown_display("always") is False

    assert settings.break_countdown_display == "tray"
    assert spy.count() == 1
