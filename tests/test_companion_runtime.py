'''Production wiring tests for the desktop companion runtime.'''

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QAbstractAnimation, QObject, QPoint, Signal, Qt
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
        self.outfit_ids = []
        self.face_cursor_calls = []
        self.gaze_directions = []
        self.move_supported = True
        self.accept_outfit = True
        self.presentation_visibility = []
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

    def set_outfit(self, outfit_id):
        self.outfit_ids.append(str(outfit_id or ''))
        return self.accept_outfit

    def has_action(self, action_id):
        return str(action_id) != 'move' or self.move_supported

    def set_suppressed(self, _suppressed):
        return None

    def set_presentation_visible(self, visible):
        self.presentation_visibility.append(bool(visible))
        self.setVisible(bool(visible))
        return True

    def set_pack(self, pet_id, _manifest):
        self.pet_id = str(pet_id)
        return True

    def set_facing_direction(self, _direction):
        return True

    def face_towards_cursor(self, position):
        self.face_cursor_calls.append(QPoint(position))
        return False

    def set_gaze_direction(self, direction):
        self.gaze_directions.append(str(direction))
        return True

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
        self.restore_values = []

    def start(self):
        self.start_calls += 1

    def stop(self, *, restore=False):
        self.stop_calls += 1
        self.restore_values.append(bool(restore))
        if restore:
            self.restore_requested.emit()


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


def test_retired_status_card_cannot_be_opened():
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

    assert runtime.show_bubble(focusable=True) is False
    runtime._toggle_pet_bubble()
    assert bubble.visible is False
    assert bubble.show_focusable is None

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


def test_presentation_applies_outfit_before_requested_action():
    QApplication.instance() or QApplication(sys.argv)
    settings = Settings(MemoryStore())
    companion = CompanionCoordinator(
        PetPackRegistry(FIXTURE_ROOT, app_version='0.8.0'),
        'snow_ferret',
    )
    controller = AppController(settings, companion=companion)
    surface = RuntimeSurface()
    bubble = FakeBubble()
    runtime = CompanionRuntime(controller, companion, surface, bubble)
    presentation = replace(
        controller.companion_presentation,
        outfit_id='snow_slope_skier',
        action_id='click_reaction',
    )

    runtime.sync_presentation(presentation)

    assert surface.outfit_ids == ['snow_slope_skier']
    assert surface.action_id == 'click_reaction'
    runtime.shutdown()
    surface.close()


def test_presentation_visibility_still_applies_when_outfit_rendering_fails():
    QApplication.instance() or QApplication(sys.argv)
    settings = Settings(MemoryStore())
    companion = CompanionCoordinator(
        PetPackRegistry(FIXTURE_ROOT, app_version='0.8.0'),
        'snow_ferret',
    )
    controller = AppController(settings, companion=companion)
    surface = RuntimeSurface()
    surface.accept_outfit = False
    bubble = FakeBubble()
    runtime = CompanionRuntime(controller, companion, surface, bubble)
    presentation = replace(
        controller.companion_presentation,
        outfit_id='snow_slope_skier',
        visible=True,
    )

    runtime.sync_presentation(presentation)

    assert surface.outfit_ids == ['snow_slope_skier']
    assert surface.presentation_visibility == [True]
    assert surface.isVisible()
    runtime.shutdown()
    surface.close()


def test_hiding_restores_transient_window_avoidance_position_once():
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
    permanent = runtime.permanent_pet_rect()
    surface.setProperty('serviceTransientPlacement', True)
    surface.move(300, 240)

    runtime.sync_presentation(
        replace(controller.companion_presentation, visible=False)
    )

    assert avoidance.restore_values[-1] is True
    assert not bool(surface.property('serviceTransientPlacement'))
    assert surface.pos() == QPoint(permanent.left, permanent.top)
    runtime.shutdown()
    surface.close()


def test_changed_edge_anchor_repositions_an_already_started_surface():
    app = QApplication.instance() or QApplication(sys.argv)
    settings = Settings(MemoryStore())
    companion = CompanionCoordinator(
        PetPackRegistry(FIXTURE_ROOT, app_version='0.7.0'),
        'snow_ferret',
    )
    controller = AppController(settings, companion=companion)
    surface = RuntimeSurface()
    bubble = FakeBubble()
    runtime = CompanionRuntime(
        controller,
        companion,
        surface,
        bubble,
        application=RuntimeApplication(),
    )
    runtime.start()

    assert controller.set_pet_anchor('top_left', 32)

    area = app.primaryScreen().availableGeometry()
    assert surface.pos() == QPoint(area.left() + 32, area.top() + 32)
    runtime.shutdown()
    surface.close()


def test_offscreen_free_anchor_is_clamped_back_to_a_visible_screen():
    app = QApplication.instance() or QApplication(sys.argv)
    settings = Settings(MemoryStore())
    settings.pet_anchor_edge = 'free'
    settings.pet_anchor_offset = 0
    settings.pet_x = 999_999
    settings.pet_y = 999_999
    companion = CompanionCoordinator(
        PetPackRegistry(FIXTURE_ROOT, app_version='0.7.0'),
        'snow_ferret',
    )
    controller = AppController(settings, companion=companion)
    surface = RuntimeSurface()
    bubble = FakeBubble()
    runtime = CompanionRuntime(
        controller,
        companion,
        surface,
        bubble,
        application=RuntimeApplication(),
    )
    runtime.start()

    area = app.primaryScreen().availableGeometry()
    assert area.left() <= surface.x() <= area.right() - surface.width() + 1
    assert area.top() <= surface.y() <= area.bottom() - surface.height() + 1
    runtime.shutdown()
    surface.close()


def test_near_cursor_dispatches_gaze_without_mirroring_whole_surface():
    QApplication.instance() or QApplication(sys.argv)
    settings = Settings(MemoryStore())
    companion = CompanionCoordinator(
        PetPackRegistry(FIXTURE_ROOT, app_version='0.8.0'),
        'snow_ferret',
    )
    controller = AppController(settings, companion=companion)
    surface = RuntimeSurface()
    surface.move(100, 100)
    surface.show()
    cursor = surface.geometry().center() + QPoint(20, 0)
    runtime = CompanionRuntime(
        controller,
        companion,
        surface,
        FakeBubble(),
        cursor_position=lambda: QPoint(cursor),
        monotonic=lambda: 10.0,
    )
    runtime._build_timers()
    runtime._last_cursor_reaction = 0.0

    runtime._probe_cursor()

    assert surface.face_cursor_calls == []
    assert surface.gaze_directions == ['right']
    assert companion.state.behavior.event_kind == 'cursor.near'
    runtime.shutdown()
    surface.close()


def test_missing_outfit_move_never_starts_window_motion(monkeypatch):
    QApplication.instance() or QApplication(sys.argv)
    settings = Settings(MemoryStore())
    companion = CompanionCoordinator(
        PetPackRegistry(FIXTURE_ROOT, app_version='0.8.0'),
        'snow_ferret',
    )
    controller = AppController(settings, companion=companion)
    surface = RuntimeSurface()
    surface.move_supported = False
    surface.move(100, 100)
    surface.show()
    bubble = FakeBubble()
    runtime = CompanionRuntime(controller, companion, surface, bubble)
    runtime._build_timers()
    companion.dispatch_kind('autonomous.move')
    monkeypatch.setattr(companion, 'start_autonomous_action', lambda: True)

    runtime._run_autonomous_action()

    assert not bool(surface.property('autonomousMoving'))
    assert runtime._autonomous_motion.state() == QAbstractAnimation.Stopped
    runtime.shutdown()
    surface.close()


def _calm_runtime(qtbot):
    from opencareyes.constants import PETS_DIR
    companion = CompanionCoordinator(PetPackRegistry(PETS_DIR), 'snow_ferret')
    controller = AppController(Settings(MemoryStore()), companion=companion)
    surface = RuntimeSurface()
    qtbot.addWidget(surface)
    bubble = FakeBubble()
    runtime = CompanionRuntime(controller, companion, surface, bubble,
                               application=RuntimeApplication())
    runtime.start()
    return runtime, controller, companion, surface, bubble


def test_right_click_close_persists_stays_closed_and_tray_restores_without_resetting_break(qtbot):
    from opencareyes.constants import PETS_DIR
    from opencareyes.ui.pet_surface import PetSurface
    from opencareyes.ui.tray_icon import TrayIcon

    store = MemoryStore()
    settings = Settings(store)
    companion = CompanionCoordinator(PetPackRegistry(PETS_DIR), 'snow_ferret')
    reminder = BreakReminder(clock=lambda: 0.0)
    controller = AppController(settings, companion=companion, break_reminder=reminder)
    surface = PetSurface()
    qtbot.addWidget(surface)
    surface.set_pack(companion.state.pet_id, companion.manifest)
    panel = QWidget()
    qtbot.addWidget(panel)
    bubble = FakeBubble()
    runtime = CompanionRuntime(controller, companion, surface, bubble, application=RuntimeApplication())
    runtime.start()
    tray = TrayIcon(controller, panel, surface, companion_runtime=runtime)
    reminder.start()
    before = controller.state.breaks
    bubble.visible = True
    qtbot.mouseClick(surface, Qt.RightButton, pos=surface.rect().center())
    assert surface._context_menu.isVisible()
    assert not bubble.isVisible()
    assert not runtime._autonomous_timer.isActive()
    assert not runtime._cursor_timer.isActive()
    # Use the actual menu hit target, not a direct controller call.
    qtbot.mouseClick(surface._context_menu, Qt.LeftButton,
                     pos=surface._context_menu.actionGeometry(surface._hide_action).center())
    assert not surface.isVisible()
    assert not controller.state.companion.enabled
    assert not Settings(store).companion_enabled
    assert not tray._pet_action.isChecked()
    controller.refresh_companion_presentation(force=True)
    runtime.sync_state(controller.state)
    assert not surface.isVisible()
    assert controller.state.breaks == before
    assert reminder._timer.isActive()
    tray._pet_action.trigger()
    assert controller.state.companion.enabled
    assert Settings(store).companion_enabled
    assert surface.isVisible()
    assert tray._pet_action.isChecked()
    assert controller.state.breaks == before
    runtime.shutdown()
    reminder.stop()


def test_cursor_gaze_reads_all_eight_screen_directions_and_central_dead_zone():
    for offset, direction in (
        ((80, 0), 'right'), ((80, -80), 'up_right'), ((0, -80), 'up'),
        ((-80, -80), 'up_left'), ((-80, 0), 'left'),
        ((-80, 80), 'down_left'), ((0, 80), 'down'), ((80, 80), 'down_right'),
        ((1, -1), 'center'), ((0, 0), 'center'),
    ):
        assert CompanionRuntime._cursor_gaze_direction(*offset) == direction


def test_open_pet_menu_blocks_cursor_and_autonomous_activity(qtbot):
    runtime, controller, companion, surface, bubble = _calm_runtime(qtbot)
    surface.setProperty('contextMenuOpen', True)
    runtime._context_menu_changed(True)
    before = companion.state.behavior
    runtime._cursor_position = lambda: surface.geometry().center() + QPoint(90, 0)
    runtime._probe_cursor()
    runtime._run_autonomous_action()
    assert companion.state.behavior == before
    assert not runtime._cursor_timer.isActive()
    assert not runtime._autonomous_timer.isActive()
    assert not runtime.can_move_for_window_avoidance()
    surface.setProperty('contextMenuOpen', False)
    runtime._context_menu_changed(False)
    assert runtime._cursor_timer.isActive()
    runtime.shutdown()


def test_manual_interaction_returns_to_focus_and_cannot_interrupt_rest(qtbot):
    runtime, controller, companion, surface, bubble = _calm_runtime(qtbot)
    controller._state = replace(controller.state, focus=replace(controller.state.focus, enabled=True))
    runtime.sync_state(controller.state)
    assert companion.state.behavior.event_kind == 'application.focus'
    assert surface.action_id == 'read'
    assert runtime.interact('item.play')
    assert surface.action_id == 'play'
    runtime._finish_pet_action('play')
    assert surface.action_id == 'read'
    bubble.is_rest_prompt_active = True
    assert not runtime.interact('item.play')
    bubble.is_rest_prompt_active = False
    controller._state = replace(controller.state, breaks=replace(controller.state.breaks, phase='resting'))
    runtime.sync_state(controller.state)
    assert surface.action_id == 'sleep'
    assert not runtime.interact('item.wave')
    runtime.shutdown()


def test_reduced_motion_manual_gesture_expires_without_stealing_new_rest(qtbot):
    runtime, controller, companion, surface, bubble = _calm_runtime(qtbot)
    runtime._application.motion_enabled = False
    runtime.set_motion_reduced(True)
    assert runtime.interact('item.play')
    assert runtime._interaction_end.isActive()
    runtime._finish_interaction()
    assert companion.state.behavior.event_kind == 'autonomous.idle'
    assert runtime.interact('item.wave')
    controller._state = replace(controller.state, breaks=replace(controller.state.breaks, phase='resting'))
    runtime.sync_state(controller.state)
    runtime._finish_interaction()
    assert companion.state.behavior.event_kind == 'rest.sleep'
    runtime.shutdown()
    assert not runtime._interaction_end.isActive()


def test_looping_outfit_wave_ends_and_cursor_gaze_continues_across_screen(qtbot):
    runtime, controller, companion, surface, bubble = _calm_runtime(qtbot)
    companion.set_outfit('snow_slope_skier')
    assert runtime.interact('item.wave')
    assert runtime._interaction_end.isActive()
    runtime._finish_interaction()
    assert companion.state.behavior.event_kind == 'autonomous.idle'
    companion.dispatch_kind('cursor.near')
    runtime._finish_pet_action('look_cursor')
    assert companion.state.behavior.event_kind == 'cursor.near'
    runtime._cursor_position = lambda: surface.geometry().center() + QPoint(500, 500)
    runtime._probe_cursor()
    assert companion.state.behavior.event_kind == 'cursor.near'
    assert surface.gaze_directions[-1] == 'down_right'
    runtime.shutdown()
