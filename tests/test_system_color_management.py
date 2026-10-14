"""Colour retirement must survive old preferences and every public UI entry."""

from __future__ import annotations

from dataclasses import replace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtTest import QTest, QSignalSpy
from PySide6.QtWidgets import QCheckBox, QLabel, QSlider

from opencareyes.application.status_presenter import StatusPresenter
from opencareyes.config.settings import Settings
from opencareyes.controller import AppController
from opencareyes.core.break_reminder import BreakReminder
from opencareyes.core.system_color import SystemManagedColor
from opencareyes.domain.runtime import DisplayPreview
from opencareyes.ui.automation_page import AutomationPage
from opencareyes.ui.blue_light_page import BlueLightPage
from opencareyes.ui.tray_icon import TrayIcon
from tests.test_controller import (
    FakeCompanion, FakeDisplayEffect, FakeFocus, FakeScheduler, MemoryStore,
)


@pytest.fixture
def system_controller(qtbot, monkeypatch):
    from opencareyes.core import blue_light_filter
    from opencareyes.platform import win32_api

    native_calls = []

    def forbidden_gamma(*args):
        native_calls.append(args)
        raise AssertionError("Tests must never touch the user's Gamma ramps")

    for module in (blue_light_filter, win32_api):
        monkeypatch.setattr(module, 'SetDeviceGammaRamp', forbidden_gamma)
        monkeypatch.setattr(module, 'GetDeviceGammaRamp', forbidden_gamma)

    store = MemoryStore()
    settings = Settings(store)
    settings.filter_enabled = True  # Existing b11 installations may opt in.
    settings.color_temperature = 3400
    settings.filter_schedule_enabled = True
    reminder = BreakReminder()
    dimmer = FakeDisplayEffect()
    service = SystemManagedColor()
    controller = AppController(
        settings, service, dimmer, reminder, FakeFocus(), FakeScheduler(),
        companion=FakeCompanion(),
    )
    yield controller, settings, dimmer, native_calls, store
    reminder.stop()
    controller._pause_timer.stop()
    controller._focus_timer.stop()
    assert not native_calls


def test_startup_preserves_old_preference_without_reapplying_colour(system_controller):
    controller, settings, _dimmer, calls, _store = system_controller
    assert settings.filter_enabled  # The saved old preference is retained.
    assert controller.restore()
    assert controller.state.display.filter_enabled is False
    assert controller.state.capabilities.filter_available is False
    assert controller.state.display_health.backend == 'windows_night_light'
    assert controller.state.effective_policy.filter.desired_enabled is False
    presentation = StatusPresenter.project(controller.state).filter
    assert presentation.status_text == '由 Windows 管理'
    assert not presentation.effective_enabled
    assert calls == []


@pytest.mark.parametrize(('profile', 'dim'), [('office', 0), ('reading', 20), ('night', 50), ('game', 0)])
def test_profiles_change_dimming_and_never_colour(system_controller, profile, dim):
    controller, settings, dimmer, _calls, _store = system_controller
    assert controller.apply_display_profile(profile)
    assert settings.dim_level == dim
    assert dimmer.enabled is (dim > 0)
    assert not settings.filter_enabled
    assert not controller.state.effective_policy.filter.effective_enabled
    assert controller.state.display_health.backend == 'windows_night_light'


def test_refresh_pause_restore_and_forged_previews_never_write_colour(system_controller):
    controller, _settings, _dimmer, calls, _store = system_controller
    assert controller.restore()
    for _ in range(10):
        intent = controller._effects.intent_from_settings()
        intent = replace(
            intent,
            desired=replace(intent.desired, filter=True, color_temperature=1000),
            preview=DisplayPreview(color_temperature=1200, dim_level=20),
        )
        assert controller._effects.reconcile(intent, force_display_commit=True).succeeded
        assert controller._blue_filter.refresh_screens()
        assert controller.pause_all(minutes=30)
        assert controller.resume_all()
        assert controller.recheck_display_capabilities()
    assert controller.restore_display_effects()
    assert controller._blue_filter.shutdown()
    assert not controller.state.effective_policy.filter.desired_enabled
    assert calls == []


def test_retired_colour_commands_report_system_management(system_controller):
    controller, _settings, _dimmer, _calls, _store = system_controller
    failures = QSignalSpy(controller.operation_failed)
    assert controller.set_color_temperature(1000) is False
    assert controller.set_filter_enabled(True) is False
    assert failures.count() == 2
    assert all(failures.at(i)[0] == 'system_color_managed' for i in range(2))


def test_keyboard_and_mouse_open_system_settings_without_changing_preferences(qtbot, monkeypatch, system_controller):
    controller, settings, dimmer, _calls, store = system_controller
    requests = []
    monkeypatch.setattr(QDesktopServices, 'openUrl', lambda uri: requests.append(uri.toString()) or True)
    page = BlueLightPage(controller)
    qtbot.addWidget(page)
    page.resize(780, 640)
    page.show()
    before = dict(store.values)
    assert [slider.accessibleName() for slider in page.findChildren(QSlider)] == ['屏幕调暗百分比']
    assert '启用色温调节' not in [box.text() for box in page.findChildren(QCheckBox)]
    QTest.mouseClick(page._night_light_button, Qt.LeftButton)
    page._night_light_button.setFocus()
    QTest.keyClick(page._night_light_button, Qt.Key_Space)
    assert controller._hotkey_callbacks()['filter']()
    assert requests == ['ms-settings:nightlight'] * 3
    assert store.values == before
    assert not dimmer.enabled
    assert not any('6500' in label.text() for label in page.findChildren(QLabel))


def test_tray_night_light_is_a_link_not_an_effect_toggle(monkeypatch, system_controller):
    controller, settings, _dimmer, _calls, store = system_controller
    requests = []
    monkeypatch.setattr(QDesktopServices, 'openUrl', lambda uri: requests.append(uri.toString()) or True)
    tray = TrayIcon(controller, object())
    try:
        assert not tray._filter_action.isCheckable()
        assert tray._filter_action.isEnabled()
        before = dict(store.values)
        tray._filter_action.trigger()
        assert requests == ['ms-settings:nightlight']
        assert store.values == before
    finally:
        tray.hide()
        tray.deleteLater()


@pytest.mark.parametrize('raises', [False, True])
def test_failed_system_settings_launch_has_actionable_feedback(monkeypatch, system_controller, raises):
    controller, settings, _dimmer, _calls, store = system_controller

    def launch(_uri):
        if raises:
            raise OSError('Settings registration unavailable')
        return False

    monkeypatch.setattr(QDesktopServices, 'openUrl', launch)
    failures = QSignalSpy(controller.operation_failed)
    before = dict(store.values)
    assert controller.open_windows_night_light() is False
    assert failures.count() == 1
    assert failures.at(0)[0] == 'night_light_settings'
    assert 'Windows 设置' in failures.at(0)[1]
    assert store.values == before


def test_automation_does_not_offer_to_pause_windows_night_light(qtbot, system_controller):
    controller, _settings, _dimmer, _calls, _store = system_controller
    page = AutomationPage(controller)
    qtbot.addWidget(page)
    assert page._rules_table.columnCount() == 4
    assert [page._rules_table.horizontalHeaderItem(i).text() for i in range(3)] == [
        '应用', '暂停休息', '隐藏专注',
    ]


def test_dimming_failure_compensates_without_a_colour_flash(system_controller):
    controller, settings, dimmer, calls, _store = system_controller
    dimmer.fail_enable = True
    assert controller.apply_display_profile('night') is False
    assert settings.filter_enabled  # Failed transaction retains old raw data.
    assert not controller.state.display.filter_enabled
    assert controller.state.display_health.backend == 'windows_night_light'
    assert not controller.state.display_health.pending
    assert calls == []
