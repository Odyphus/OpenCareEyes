'''Production wiring tests for the desktop companion runtime.'''

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QObject, QPoint, Signal
from PySide6.QtWidgets import QApplication, QWidget

from opencareyes.application.companion_coordinator import CompanionCoordinator
from opencareyes.application.companion_runtime import CompanionRuntime
from opencareyes.application.pet_pack_registry import PetPackRegistry
from opencareyes.config.settings import Settings
from opencareyes.controller import AppController
from opencareyes.core.break_reminder import BreakReminder
from opencareyes.state import BreakPromptState, BreakState, GlobalPauseState


FIXTURE_ROOT = Path(__file__).parent / 'fixtures' / 'pets'


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
        return None

    def clear(self):
        self.values.clear()

    def remove(self, key):
        self.values.pop(key, None)


class FakeSurface:
    def __init__(self):
        self.actions: list[tuple[str, bool]] = []
        self.reduced_motion = False

    def play_action(self, action_id: str, *, restart: bool = False):
        self.actions.append((action_id, restart))
        return True

    def set_reduced_motion(self, reduced: bool):
        self.reduced_motion = bool(reduced)


class FakeBubble(QObject):
    start_due_requested = Signal()
    snooze_requested = Signal(int)
    skip_requested = Signal()
    dismissed = Signal()
    tool_requested = Signal(str)
    item_requested = Signal(str)

    def __init__(self):
        super().__init__()
        self.is_rest_prompt_active = False
        self.visible = False
        self.status = ('', '')
        self.countdown = (0, 0)
        self.quick_actions = ()
        self.show_focusable = None

    def show_rest_prompt(self, _anchor, **_kwargs):
        self.is_rest_prompt_active = True
        self.visible = True

    def clear_rest_prompt(self):
        self.is_rest_prompt_active = False
        self.visible = False

    def hide(self):
        self.visible = False

    def isVisible(self):
        return self.visible

    def toggle_for(self, _anchor, *, focusable=False):
        self.show_focusable = bool(focusable)
        self.visible = not self.visible

    def show_for(self, _anchor, *, focusable=False):
        self.show_focusable = bool(focusable)
        self.visible = True

    def set_status(self, title, detail):
        self.status = (title, detail)

    def set_break_countdown(self, remaining, total):
        self.countdown = (remaining, total)

    def set_quick_actions(self, actions):
        self.quick_actions = tuple(actions)

    def set_theme(self, _snapshot):
        return None


class FakeAnimator(QObject):
    animation_finished = Signal(str)


class RuntimeSurface(QWidget):
    position_changed = Signal(int, int)
    reset_requested = Signal()
    pet_event = Signal(str, object)
    pack_switched = Signal(str)
    pack_switch_failed = Signal(str, str)
    bubble_requested = Signal()

    def __init__(self):
        super().__init__()
        self.animator = FakeAnimator(self)
        self.pet_id = 'snow_ferret'
        self._action_id = 'idle'
        self._dragging = False
        self._reduced_motion = False
        self.setFixedSize(64, 64)

    @property
    def action_id(self):
        return self._action_id

    @property
    def is_dragging(self):
        return self._dragging

    def play_action(self, action_id: str, *, restart: bool = False):
        del restart
        self._action_id = str(action_id)
        return True

    def set_reduced_motion(self, reduced: bool):
        self._reduced_motion = bool(reduced)

    def set_scale_percent(self, _percent):
        return None

    def set_appearance(self, _appearance):
        return None

    def set_suppressed(self, _suppressed):
        return None

    def set_presentation_visible(self, visible):
        self.setVisible(bool(visible))
        return True

    def set_pack(self, pet_id, _manifest):
        self.pet_id = str(pet_id)
        return True

    def set_facing_direction(self, _direction):
        return True

    def face_towards_cursor(self, _position):
        return False

    def move_to_default(self):
        self.move(10, 10)


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


class FakeWindowAvoidance(QObject):
    move_requested = Signal(object)
    restore_requested = Signal()

    def __init__(self):
        super().__init__()
        self.start_calls = 0
        self.stop_calls = 0

    def start(self):
        self.start_calls += 1

    def stop(self, *, restore=False):
        del restore
        self.stop_calls += 1


def test_break_end_restores_idle_in_same_event_loop():
    QApplication.instance() or QApplication(sys.argv)
    settings = Settings(MemoryStore())
    reminder = BreakReminder()
    companion = CompanionCoordinator(
        PetPackRegistry(FIXTURE_ROOT, app_version='0.7.0'),
        'snow_ferret',
    )
    controller = AppController(
        settings,
        break_reminder=reminder,
        companion=companion,
    )
    surface = FakeSurface()
    bubble = FakeBubble()
    runtime = CompanionRuntime(controller, companion, surface, bubble)
    controller.state_changed.connect(runtime.sync_state)
    runtime.sync_state(controller.state)

    reminder.start()
    assert reminder.start_break_now('short') is True
    assert companion.state.behavior.event_kind == 'rest.sleep'
    assert surface.actions[-1] == ('sleep', True)

    assert controller.skip_break() is True

    assert reminder.phase == 'working'
    assert companion.state.behavior.event_kind == 'autonomous.idle'
    assert surface.actions[-1] == ('idle', True)
    assert bubble.is_rest_prompt_active is False
    assert bubble.visible is False
    runtime.shutdown()
    reminder.stop()


def test_reduced_motion_stops_activity_and_restores_permanent_anchor():
    QApplication.instance() or QApplication(sys.argv)
    settings = Settings(MemoryStore())
    companion = CompanionCoordinator(
        PetPackRegistry(FIXTURE_ROOT, app_version='0.7.0'),
        'snow_ferret',
    )
    controller = AppController(settings, companion=companion)
    surface = RuntimeSurface()
    bubble = FakeBubble()
    application = RuntimeApplication()
    avoidance = FakeWindowAvoidance()
    runtime = CompanionRuntime(
        controller,
        companion,
        surface,
        bubble,
        application=application,
    )
    runtime.attach_window_avoidance(avoidance)
    runtime.start()

    assert avoidance.start_calls == 1
    assert runtime._autonomous_timer.isActive() is True
    assert companion.dispatch_kind('autonomous.move') is True
    surface.setProperty('autonomousMoving', True)
    surface.setProperty('serviceTransientPlacement', True)
    surface.move(200, 200)

    application.motion_enabled = False
    runtime.set_motion_reduced(True)

    anchor = runtime.permanent_pet_rect()
    assert surface.pos() == QPoint(anchor.left, anchor.top)
    assert companion.state.behavior.event_kind == 'autonomous.idle'
    assert runtime._autonomous_timer.isActive() is False
    assert runtime._cursor_timer.isActive() is False
    assert avoidance.stop_calls == 1

    runtime.set_motion_reduced(True)
    assert avoidance.stop_calls == 1

    application.motion_enabled = True
    runtime.set_motion_reduced(False)
    assert avoidance.start_calls == 2
    assert runtime._autonomous_timer.isActive() is True
    runtime.set_motion_reduced(False)
    assert avoidance.start_calls == 2

    runtime.shutdown()
    surface.close()


def test_explicit_bubble_entry_can_request_keyboard_focus():
    QApplication.instance() or QApplication(sys.argv)
    settings = Settings(MemoryStore())
    companion = CompanionCoordinator(
        PetPackRegistry(FIXTURE_ROOT, app_version='0.7.0'),
        'snow_ferret',
    )
    controller = AppController(settings, companion=companion)
    surface = RuntimeSurface()
    surface.show()
    bubble = FakeBubble()
    runtime = CompanionRuntime(controller, companion, surface, bubble)

    assert runtime.show_bubble(focusable=True) is True
    assert bubble.visible is True
    assert bubble.show_focusable is True

    runtime.shutdown()
    surface.close()


def test_global_pause_clears_due_visual_and_restores_latest_prompt_once():
    QApplication.instance() or QApplication(sys.argv)
    settings = Settings(MemoryStore())
    companion = CompanionCoordinator(
        PetPackRegistry(FIXTURE_ROOT, app_version='0.7.0'),
        'snow_ferret',
    )
    controller = AppController(settings, companion=companion)
    surface = FakeSurface()
    bubble = FakeBubble()
    runtime = CompanionRuntime(controller, companion, surface, bubble)
    due = replace(
        controller.state,
        breaks=BreakState(enabled=True, phase='prompting'),
        break_prompt=BreakPromptState(kind='short', stage='gentle'),
    )

    runtime.sync_state(due)
    assert companion.state.behavior.event_kind == 'break.due'
    assert bubble.is_rest_prompt_active is True

    paused = replace(
        due,
        global_pause=GlobalPauseState(active=True, mode='duration'),
    )
    runtime.sync_state(paused)
    assert companion.state.behavior.event_kind == 'autonomous.idle'
    assert bubble.is_rest_prompt_active is False
    action_count = len(surface.actions)

    runtime.sync_state(paused)
    assert len(surface.actions) == action_count

    runtime.sync_state(due)
    assert companion.state.behavior.event_kind == 'break.due'
    assert bubble.is_rest_prompt_active is True
    assert len(surface.actions) == action_count + 1
    runtime.shutdown()


def test_safety_suppression_clears_rest_visual_and_restores_active_rest():
    QApplication.instance() or QApplication(sys.argv)
    settings = Settings(MemoryStore())
    companion = CompanionCoordinator(
        PetPackRegistry(FIXTURE_ROOT, app_version='0.7.0'),
        'snow_ferret',
    )
    controller = AppController(settings, companion=companion)
    surface = FakeSurface()
    bubble = FakeBubble()
    runtime = CompanionRuntime(controller, companion, surface, bubble)
    resting = replace(
        controller.state,
        breaks=BreakState(enabled=True, phase='resting'),
    )

    runtime.sync_state(resting)
    assert companion.state.behavior.event_kind == 'rest.sleep'

    for reason in ('fullscreen', 'locked'):
        suppressed = replace(
            resting,
            companion=replace(
                resting.companion,
                visible=False,
                suppressed_by=(reason,),
            ),
        )
        runtime.sync_state(suppressed)
        assert companion.state.behavior.event_kind == 'autonomous.idle'
        assert bubble.is_rest_prompt_active is False

        runtime.sync_state(resting)
        assert companion.state.behavior.event_kind == 'rest.sleep'

    runtime.shutdown()
