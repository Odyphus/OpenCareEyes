"""Manual dimming must stay stable across upgrades, contexts and restarts."""

from dataclasses import replace
import gc

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QPushButton, QSlider

from opencareyes.config.settings import SCHEMA_VERSION, Settings
from opencareyes.controller import AppController
from opencareyes.core.system_color import SystemManagedColor
from opencareyes.domain.context import FeatureSuppression, SuppressionDecision
from opencareyes.ui.blue_light_page import BlueLightPage
from opencareyes.ui.tray_icon import TrayIcon
from tests.test_controller import FakeDisplayEffect, FakeFocus, FakeScheduler
from tests.test_settings import MemoryStore


class RecordingDimmer(FakeDisplayEffect):
    def __init__(self):
        super().__init__()
        self.calls = []

    def enable(self, level=None):
        self.calls.append(('enable', level))
        super().enable(level)

    def disable(self):
        self.calls.append(('disable',))
        super().disable()

    def set_brightness(self, value):
        self.calls.append(('level', value))
        super().set_brightness(value)


@pytest.fixture
def manual_controller(qtbot, monkeypatch):
    from opencareyes.platform import win32_api
    from opencareyes.core import blue_light_filter

    def forbidden_gamma(*_args):
        raise AssertionError('Manual dimming must never read or write Gamma')

    for module in (win32_api, blue_light_filter):
        monkeypatch.setattr(module, 'GetDeviceGammaRamp', forbidden_gamma)
        monkeypatch.setattr(module, 'SetDeviceGammaRamp', forbidden_gamma)
    store = MemoryStore()
    settings = Settings(store)
    dimmer = RecordingDimmer()
    scheduler = FakeScheduler()
    controller = AppController(
        settings, SystemManagedColor(), dimmer, focus_mode=FakeFocus(),
        scheduler=scheduler, manual_dimming_only=True,
    )
    yield controller, settings, dimmer, store, scheduler
    controller._pause_timer.stop()
    controller._focus_timer.stop()


def test_upgrade_opts_out_once_and_preserves_other_preferences():
    original = {
        'meta/schema_version': 7, 'dimmer/enabled': True, 'dimmer/level': 64,
        'filter/schedule_enabled': True, 'preset/current': 'night',
        'general/theme': 'dark', 'general/autostart': True,
        'companion/enabled': False, 'break/work_duration': 900,
        'filter/temperature': 3400,
    }
    store = MemoryStore(original)
    settings = Settings(store)
    assert settings.stored_schema_version == SCHEMA_VERSION
    assert not settings.dimmer_enabled
    assert not settings.filter_schedule_enabled
    assert settings.dim_level == 64
    assert settings.current_preset == 'custom'
    changed = {key for key in original if original[key] != store.values[key]}
    assert changed == {
        'meta/schema_version', 'dimmer/enabled', 'filter/schedule_enabled', 'preset/current',
    }
    settings.dimmer_enabled = True
    settings.sync()
    store.writes.clear()
    restarted = Settings(store)
    assert restarted.stored_schema_version == SCHEMA_VERSION
    assert restarted.dimmer_enabled
    assert restarted.dim_level == 64
    assert store.writes == []


def test_upgrade_keeps_an_old_schedule_pause_until_manual_resume():
    store = MemoryStore({
        'meta/schema_version': 7, 'pause/mode': 'next_schedule', 'pause/until': '',
    })
    settings = Settings(store)
    assert settings.global_pause_mode == 'manual'
    assert settings.global_pause_until is None


def test_slider_does_not_enable_dimming_and_manual_choice_survives_restart(manual_controller):
    controller, settings, dimmer, store, _scheduler = manual_controller
    assert controller.restore()
    assert not dimmer.enabled
    assert controller.set_dim_level(50)
    assert settings.dim_level == 50
    assert not dimmer.enabled
    assert not settings.dimmer_enabled
    assert controller.set_feature_enabled('dimmer', True)
    assert dimmer.enabled and dimmer.level == 50
    assert controller.set_dim_level(80)

    for enabled in (True, False):
        assert controller.set_feature_enabled('dimmer', enabled)
        restarted_dimmer = RecordingDimmer()
        restarted = AppController(
            Settings(store), SystemManagedColor(), restarted_dimmer,
            manual_dimming_only=True,
        )
        assert restarted.restore()
        assert restarted.state.display.dimmer_enabled is enabled
        assert restarted_dimmer.enabled is enabled
        assert restarted.state.display.dim_level == 80


def test_legacy_schedule_and_profile_requests_cannot_change_brightness(manual_controller):
    controller, settings, dimmer, store, scheduler = manual_controller
    # Even stale preferences supplied after migration cannot start a scheduler.
    settings.filter_schedule_enabled = True
    assert controller.restore()
    assert controller.set_dim_level(40)
    assert controller.set_feature_enabled('dimmer', True)
    before = dict(store.values)
    calls = list(dimmer.calls)
    assert not controller.state.automation.enabled
    assert not controller.state.capabilities.automation_available
    assert not scheduler.running
    assert scheduler.callback is None
    for profile in ('office', 'reading', 'night', 'game'):
        assert controller.apply_display_profile(profile) is False
        controller._on_scheduled_profile_requested(profile)
        controller._on_scheduled_filter_state_requested(True)
    assert controller.set_schedule(True, mode='fixed') is False
    assert controller.pause_all(until_next_schedule=True) is False
    assert store.values == before
    assert dimmer.calls == calls
    assert dimmer.enabled and dimmer.level == 40


def test_repeated_application_contexts_never_toggle_manual_dimming(manual_controller):
    controller, _settings, dimmer, _store, _scheduler = manual_controller
    assert controller.restore()
    assert controller.set_dim_level(60)
    assert controller.set_feature_enabled('dimmer', True)
    assert controller.set_feature_enabled('focus', True)
    calls = list(dimmer.calls)
    for _ in range(20):
        intent = controller._effects.intent_from_settings(suppression=SuppressionDecision(
            dimmer=FeatureSuppression(('app:demo.exe',), 'leave_application'),
            focus=FeatureSuppression(('app:demo.exe',), 'leave_application'),
        ))
        result = controller._effects.reconcile(intent)
        assert result.policy.dimmer.effective_enabled
        assert not result.policy.dimmer.suppressed_by
        assert not result.policy.focus.effective_enabled
        result = controller._effects.reconcile(replace(intent, suppression=SuppressionDecision()))
        assert result.policy.focus.effective_enabled
    assert dimmer.calls == calls
    assert dimmer.enabled and dimmer.level == 60
    assert controller.pause_all(minutes=None)
    assert not dimmer.enabled
    assert controller.resume_all()
    assert dimmer.enabled and dimmer.level == 60


def test_screen_keyboard_and_tray_control_the_same_manual_setting(qtbot, manual_controller):
    controller, settings, dimmer, _store, _scheduler = manual_controller
    page = BlueLightPage(controller)
    qtbot.addWidget(page)
    page.show()
    assert len(page.findChildren(QSlider)) == 1
    assert not {'办公', '阅读', '夜间', '游戏'}.intersection(
        button.text() for button in page.findChildren(QPushButton)
    )
    page._dim_slider.setFocus()
    QTest.keyClick(page._dim_slider, Qt.Key_PageUp)
    assert settings.dim_level == 20
    assert not dimmer.enabled
    page._dimmer_toggle.setChecked(True)
    assert dimmer.enabled and dimmer.level == 20

    class Panel:
        def show_page(self, _name):
            pass

    tray = TrayIcon(controller, Panel())
    try:
        def labels(menu):
            for action in menu.actions():
                yield action.text()
                if action.menu() is not None:
                    yield from labels(action.menu())
        texts = set(labels(tray.contextMenu()))
        assert not {'调暗方案', '自动日程…', '直到下一次自动切换'}.intersection(texts)
        assert '免打扰…' in texts
        # Repeated native-menu inspection and wrapper collection must not
        # destroy actions before a controller update (observed on CI 3.11).
        for _ in range(10):
            assert set(labels(tray.contextMenu())) == texts
            gc.collect()
            controller.refresh_state()
        tray._dimmer_action.trigger()
        assert not settings.dimmer_enabled and not dimmer.enabled
    finally:
        tray.hide()
        tray.deleteLater()
