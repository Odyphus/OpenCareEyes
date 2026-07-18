'''v0.7 contracts that keep high-frequency UI work off the full AppState path.'''

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QAbstractAnimation, QObject, QPoint, QTimer, Signal
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from opencareyes.application.companion_coordinator import CompanionCoordinator
from opencareyes.application.companion_runtime import CompanionRuntime
from opencareyes.application.pet_pack_registry import PetPackRegistry
from opencareyes.application.utility_timer import UtilityTimerService
from opencareyes.config.settings import Settings
from opencareyes.controller import AppController
from opencareyes.core.break_reminder import BreakReminder
from opencareyes.ui.pet_surface import PetSurface


FIXTURE_ROOT = Path(__file__).parent / 'fixtures' / 'pets'


class MemoryStore:
    def __init__(self):
        self.values = {}

    def value(self, key, default=None, type=None):
        value = self.values.get(key, default)
        return type(value) if type is not None and value is not None else value

    def setValue(self, key, value):
        self.values[key] = value

    def allKeys(self):
        return list(self.values)

    def sync(self):
        return None

    def clear(self):
        self.values.clear()

    def remove(self, key):
        self.values.pop(key, None)


class Bubble(QObject):
    start_due_requested = Signal()
    snooze_requested = Signal(int)
    skip_requested = Signal()
    dismissed = Signal()
    tool_requested = Signal(str)
    item_requested = Signal(str)

    def __init__(self):
        super().__init__()
        self.is_rest_prompt_active = False
        self._visible = False

    def show_rest_prompt(self, _anchor, **_kwargs):
        self.is_rest_prompt_active = True
        self._visible = True

    def clear_rest_prompt(self):
        self.is_rest_prompt_active = False
        self._visible = False

    def show_for(self, _anchor, *, focusable=False):
        del focusable
        self._visible = True

    def toggle_for(self, _anchor, *, focusable=False):
        del focusable
        self._visible = not self._visible

    def hide(self):
        self._visible = False

    def isVisible(self):
        return self._visible

    def set_status(self, _title, _detail):
        return None

    def set_break_countdown(self, _remaining, _total):
        return None

    def set_quick_actions(self, _actions):
        return None

    def set_theme(self, _snapshot):
        return None


class RuntimeApplication(QObject):
    motion_changed = Signal(bool)

    def __init__(self):
        super().__init__()
        self.motion_enabled = True

    def topLevelWidgets(self):
        return QApplication.topLevelWidgets()

    def screenAt(self, point):
        return QApplication.screenAt(point)

    def primaryScreen(self):
        return QApplication.primaryScreen()

    def set_pet_accent(self, _accent):
        return None


def _runtime(*, monotonic=lambda: 0.0, cursor_position=lambda: QPoint()):
    settings = Settings(MemoryStore())
    settings.companion_enabled = True
    companion = CompanionCoordinator(
        PetPackRegistry(FIXTURE_ROOT, app_version='0.7.0'),
        'snow_ferret',
    )
    controller = AppController(settings, companion=companion)
    surface = PetSurface()
    bubble = Bubble()
    runtime = CompanionRuntime(
        controller,
        companion,
        surface,
        bubble,
        application=RuntimeApplication(),
        monotonic=monotonic,
        cursor_position=cursor_position,
    )
    runtime.start()
    return controller, surface, runtime


def test_dedicated_ticks_and_stable_semantics_never_build_full_state(
    qtbot,
    monkeypatch,
):
    settings = Settings(MemoryStore())
    reminder = BreakReminder()
    timer = UtilityTimerService()
    controller = AppController(
        settings,
        break_reminder=reminder,
        utility_timer=timer,
    )
    full_state = QSignalSpy(controller.state_changed)
    break_ticks = QSignalSpy(controller.break_tick)
    utility_ticks = QSignalSpy(controller.utility_timer_tick)
    state_before = controller.state

    def reject_full_state_build(*_args, **_kwargs):
        raise AssertionError('high-frequency event rebuilt the complete AppState')

    monkeypatch.setattr(controller, '_build_state', reject_full_state_build)

    controller._on_break_tick(59, 1200)
    timer.tick.emit(58)
    for _ in range(10):
        controller._on_break_service_state_changed()
        controller.refresh_companion_presentation()

    assert break_ticks.at(0) == [59, 1200]
    assert utility_ticks.at(0) == [58]
    assert full_state.count() == 0
    assert controller.state is state_before
    reminder.stop()


def test_pet_events_cursor_probe_and_frame_step_use_presentation_only(
    qtbot,
    monkeypatch,
):
    now = [0.0]
    cursor = [QPoint()]
    controller, surface, runtime = _runtime(
        monotonic=lambda: now[0],
        cursor_position=lambda: cursor[0],
    )
    qtbot.addWidget(surface)
    full_state = QSignalSpy(controller.state_changed)
    presentation = QSignalSpy(controller.companion_presentation_changed)
    state_before = controller.state

    def reject_full_state_build(*_args, **_kwargs):
        raise AssertionError('pet activity rebuilt the complete AppState')

    monkeypatch.setattr(controller, '_build_state', reject_full_state_build)

    assert runtime.dispatch_pet_event('click') is True
    cursor[0] = surface.geometry().center()
    now[0] = 3.0
    runtime._probe_cursor()
    surface.animator._advance()
    for _ in range(10):
        runtime.sync_state(controller.state)

    assert presentation.count() >= 1
    assert full_state.count() == 0
    assert controller.state is state_before
    runtime.shutdown()
    surface.close()


def test_hidden_or_reduced_companion_has_no_active_activity_clock(qtbot):
    controller, surface, runtime = _runtime()
    del controller
    qtbot.addWidget(surface)
    assert surface.isVisible()
    assert runtime._cursor_timer.isActive()
    assert runtime._autonomous_timer.isActive()
    assert not surface.animator.is_running

    runtime.set_motion_reduced(True)

    assert not any(timer.isActive() for timer in surface.findChildren(QTimer))
    assert runtime._autonomous_motion.state() == QAbstractAnimation.Stopped
    assert not surface.animator.is_running

    runtime.set_motion_reduced(False)
    assert runtime._cursor_timer.isActive()
    surface.hide()
    runtime._refresh_timer_state()

    assert not any(timer.isActive() for timer in surface.findChildren(QTimer))
    assert runtime._autonomous_motion.state() == QAbstractAnimation.Stopped
    assert not surface.animator.is_running
    runtime.shutdown()
    surface.close()
