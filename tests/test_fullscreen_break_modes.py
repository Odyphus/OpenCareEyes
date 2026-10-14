"""Full-screen break choices must affect real counting and prompt routing."""

from dataclasses import replace
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt

from opencareyes.application.companion_runtime import CompanionRuntime
from opencareyes.application.context_coordinator import ContextCoordinator
from opencareyes.config.settings import SCHEMA_VERSION, Settings
from opencareyes.controller import AppController
from opencareyes.core.break_reminder import BreakReminder
from opencareyes.core.system_color import SystemManagedColor
from opencareyes.domain.context import AutoPausePreferences, ContextSnapshot
from opencareyes.domain.policy import AutoPausePolicy
from opencareyes.state import (
    AppState, BreakPromptState, BreakState, ContextState, EffectivePolicyState,
    FeatureRuntimeState, PetState,
)
from opencareyes.ui.break_page import BreakPage
from opencareyes.ui.break_prompt import BreakPrompt
from opencareyes.ui.tray_icon import TrayIcon
from tests.test_context_coordination import FakeSensor
from tests.test_controller import FakeDisplayEffect, FakeFocus
from tests.test_settings import MemoryStore


@pytest.mark.parametrize('mode', ['continue', 'pause'])
@pytest.mark.parametrize('smart_enabled', [False, True])
@pytest.mark.parametrize('notification_mode', ['normal', 'presentation', 'd3d_fullscreen'])
def test_explicit_choice_survives_no_mouse_input(mode, smart_enabled, notification_mode):
    decision = AutoPausePolicy.evaluate(
        ContextSnapshot(fullscreen=True, notification_mode=notification_mode, idle_seconds=720),
        AutoPausePreferences(
            smart_pause_enabled=smart_enabled, fullscreen_break_mode=mode,
        ), (),
    )
    assert decision.breaks.suppressed is (mode == 'pause')
    assert 'idle' not in decision.breaks.suppressed_by
    assert not decision.natural_rest


@pytest.mark.parametrize('mode', ['continue', 'pause'])
@pytest.mark.parametrize('session', ['locked', 'suspended'])
def test_fullscreen_choice_never_overrides_lock_or_sleep(mode, session):
    decision = AutoPausePolicy.evaluate(
        ContextSnapshot(session=session, fullscreen=True, idle_seconds=720),
        AutoPausePreferences(smart_pause_enabled=False, fullscreen_break_mode=mode), (),
    )
    assert decision.breaks.suppressed
    assert decision.natural_rest


@pytest.mark.parametrize('old_paused', [False, True])
def test_upgrade_keeps_choice_and_separates_focus_setting(old_paused):
    store = MemoryStore({
        'meta/schema_version': 8, 'context/fullscreen_pause_enabled': old_paused,
        'dimmer/enabled': True, 'dimmer/level': 70, 'general/theme': 'dark',
    })
    settings = Settings(store)
    assert settings.stored_schema_version == SCHEMA_VERSION
    assert settings.fullscreen_break_mode == ('pause' if old_paused else 'continue')
    assert settings.dimmer_enabled and settings.dim_level == 70
    assert settings.theme == 'dark'
    settings.fullscreen_break_mode = 'continue'
    settings.fullscreen_pause_enabled = True
    assert settings.fullscreen_break_mode == 'continue'
    settings.fullscreen_pause_enabled = False
    assert settings.fullscreen_break_mode == 'continue'
    settings.fullscreen_break_mode = 'pause'
    settings.sync_checked()
    assert Settings(store).fullscreen_break_mode == 'pause'
    with pytest.raises(ValueError):
        settings.fullscreen_break_mode = 'game'


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


@pytest.fixture
def fullscreen_controller(qtbot):
    clock = Clock()
    settings = Settings(MemoryStore())
    settings.break_enabled = True
    settings.break_mode = 'custom'
    settings.cadence_mode = 'custom'
    settings.cadence_short_interval = 60
    settings.cadence_short_duration = 20
    settings.cadence_long_enabled = False
    settings.smart_pause_enabled = False
    settings.break_reminder_style = 'progressive'
    reminder = BreakReminder(clock=clock)
    controller = AppController(
        settings, SystemManagedColor(), FakeDisplayEffect(), reminder, FakeFocus(),
        manual_dimming_only=True,
    )
    sensor = FakeSensor()
    runtime = ContextCoordinator(settings, sensor, controller._effects)
    controller.attach_context_runtime(runtime)
    assert controller.restore()
    yield controller, settings, reminder, sensor, runtime, clock
    reminder.stop()
    runtime.stop()
    controller._pause_timer.stop()
    controller._focus_timer.stop()


def enter_fullscreen(sensor, runtime):
    sensor.current_snapshot = ContextSnapshot(
        foreground_app_id='player.exe', fullscreen=True,
        notification_mode='normal', idle_seconds=720,
    )
    runtime.recompute()


def test_continue_counts_and_reaches_due_while_passively_fullscreen(fullscreen_controller):
    controller, _settings, reminder, sensor, runtime, clock = fullscreen_controller
    assert controller.set_fullscreen_break_mode('continue')
    enter_fullscreen(sensor, runtime)
    clock.advance(20)
    reminder._on_tick()
    assert reminder.remaining == 40
    assert not reminder.suspended
    clock.advance(40)
    reminder._on_tick()
    assert reminder.phase == 'prompting'
    assert controller.state.break_prompt.stage == 'gentle'
    assert not controller.state.effective_policy.breaks.suppressed_by


@pytest.mark.parametrize('strict', [False, True])
def test_pause_preserves_remainder_and_resumes_after_fullscreen(fullscreen_controller, strict):
    controller, _settings, reminder, sensor, runtime, clock = fullscreen_controller
    assert controller.set_force_break(strict)
    clock.advance(10)
    reminder._on_tick()
    assert reminder.remaining == 50
    enter_fullscreen(sensor, runtime)
    assert reminder.suspended
    clock.advance(720)
    reminder._on_tick()
    assert reminder.remaining == 50
    assert controller.state.break_prompt.stage in {'none', 'hidden'}
    sensor.current_snapshot = ContextSnapshot(notification_mode='normal', idle_seconds=0)
    runtime.recompute()
    assert not reminder.suspended
    assert reminder.remaining == 50
    clock.advance(10)
    reminder._on_tick()
    assert reminder.remaining == 40


def test_switching_mode_while_fullscreen_updates_counting_and_saved_choice(fullscreen_controller):
    controller, settings, reminder, sensor, runtime, clock = fullscreen_controller
    enter_fullscreen(sensor, runtime)
    assert reminder.suspended
    assert controller.set_fullscreen_break_mode('continue')
    assert not reminder.suspended
    clock.advance(15)
    reminder._on_tick()
    assert reminder.remaining == 45
    assert controller.set_fullscreen_break_mode('pause')
    assert reminder.suspended
    clock.advance(100)
    reminder._on_tick()
    assert reminder.remaining == 45
    assert Settings(settings._s).fullscreen_break_mode == 'pause'
    assert not controller.set_fullscreen_break_mode('video')
    assert settings.fullscreen_break_mode == 'pause'


def test_break_page_names_modes_by_behaviour_and_does_not_change_focus(qtbot, fullscreen_controller):
    controller, settings, _reminder, _sensor, _runtime, _clock = fullscreen_controller
    page = BreakPage(controller)
    qtbot.addWidget(page)
    combo = page._fullscreen_mode_combo
    assert [combo.itemText(i) for i in range(combo.count())] == [
        '继续计时并提醒', '暂停计时',
    ]
    old_focus = settings.fullscreen_pause_enabled
    combo.setCurrentIndex(combo.findData('continue'))
    assert settings.fullscreen_break_mode == 'continue'
    assert settings.fullscreen_pause_enabled is old_focus
    assert '不动鼠标' in page._fullscreen_mode_hint.text()
    combo.setCurrentIndex(combo.findData('pause'))
    assert settings.fullscreen_break_mode == 'pause'
    assert '剩余时间' in page._fullscreen_mode_hint.text()


def test_tray_and_break_page_share_the_choice(qtbot, fullscreen_controller):
    controller, settings, _reminder, _sensor, _runtime, _clock = fullscreen_controller
    page = BreakPage(controller)
    qtbot.addWidget(page)
    tray = TrayIcon(controller, SimpleNamespace(show_page=lambda _name: None))
    try:
        tray._fullscreen_break_actions['continue'].trigger()
        assert settings.fullscreen_break_mode == 'continue'
        assert page._fullscreen_mode_combo.currentData() == 'continue'
        assert tray._fullscreen_break_actions['continue'].isChecked()
        page._fullscreen_mode_combo.setCurrentIndex(page._fullscreen_mode_combo.findData('pause'))
        assert tray._fullscreen_break_actions['pause'].isChecked()
    finally:
        tray.hide()
        tray.deleteLater()


@pytest.mark.parametrize('notification_mode', ['normal', 'presentation', 'd3d_fullscreen'])
def test_fullscreen_progressive_prompt_uses_corner_even_with_floating_pet(qtbot, notification_mode):
    state = AppState(
        breaks=BreakState(
            enabled=True, phase='prompting', countdown_display='floating',
            reminder_style='progressive', fullscreen_mode='continue',
        ),
        context=ContextState(fullscreen=True, notification_mode=notification_mode),
        companion=PetState(visible=False),
        break_prompt=BreakPromptState(stage='gentle'),
    )
    prompt = BreakPrompt()
    qtbot.addWidget(prompt)
    prompt.render(state)
    assert prompt.isVisible()
    assert prompt.windowFlags() & Qt.WindowStaysOnTopHint
    assert prompt.testAttribute(Qt.WA_ShowWithoutActivating)
    cleared = []
    shown = []
    runtime = SimpleNamespace(_bubble=SimpleNamespace(
        clear_rest_prompt=lambda: cleared.append(True),
        show_rest_prompt=lambda *_a, **_k: shown.append(True),
    ))
    CompanionRuntime._sync_break_prompt(runtime, state)
    assert cleared == [True] and shown == []
    prompt.render(replace(state, effective_policy=EffectivePolicyState(
        breaks=FeatureRuntimeState(suppressed_by=('fullscreen',)),
    )))
    assert not prompt.isVisible()
