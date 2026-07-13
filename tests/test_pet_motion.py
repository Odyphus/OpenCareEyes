"""Animation, theme and system-preference tests for the countdown pet."""

from dataclasses import replace

from PySide6.QtCore import QAbstractAnimation, QObject, QPoint, Signal
from PySide6.QtWidgets import QApplication

import opencareyes.app as app_module
from opencareyes.app import OpenCareEyesApp
from opencareyes.state import (
    AppState,
    BreakState,
    EffectivePolicyState,
    FeatureRuntimeState,
)
from opencareyes.ui.mini_countdown import MiniCountdownWidget


class _Controller(QObject):
    state_changed = Signal(object)

    def __init__(self, state: AppState):
        super().__init__()
        self.state = state

    def publish(self, state: AppState) -> None:
        self.state = state
        self.state_changed.emit(state)

    def set_break_countdown_display(self, mode: str) -> bool:
        self.publish(
            replace(
                self.state,
                breaks=replace(self.state.breaks, countdown_display=mode),
            )
        )
        return True


def _state(*, phase: str = "working", remaining: int = 83) -> AppState:
    return AppState(
        breaks=BreakState(
            enabled=True,
            phase=phase,
            remaining=remaining,
            total=1200,
            countdown_display="floating",
        )
    )


def test_pet_animation_timings_and_repeated_state_do_not_restart(qtbot):
    controller = _Controller(_state())
    pet = MiniCountdownWidget(controller)
    qtbot.addWidget(pet)

    assert pet._fade_animation.duration() == 160
    assert pet._mood_animation.duration() == 180
    assert pet._blink_timer.interval() == 15_000
    assert pet._blink_close_timer.interval() == 160

    resting = _state(phase="resting")
    controller.publish(resting)
    assert pet._mood_animation.state() == QAbstractAnimation.Running
    pet._mood_animation.setCurrentTime(90)

    controller.publish(resting)
    assert pet._mood_animation.currentTime() >= 90


def test_reduced_motion_stops_and_snaps_all_animation(qtbot):
    controller = _Controller(_state())
    pet = MiniCountdownWidget(controller)
    qtbot.addWidget(pet)
    controller.publish(_state(phase="resting"))

    pet.set_motion_mode("reduced")

    assert not pet.motion_enabled
    assert pet._fade_animation.state() == QAbstractAnimation.Stopped
    assert pet._mood_animation.state() == QAbstractAnimation.Stopped
    assert not pet._blink_timer.isActive()
    assert not pet._blink_close_timer.isActive()
    assert not pet._pet.blinking
    assert pet.windowOpacity() == 1.0
    assert pet._accent == pet._target_accent


def test_working_pet_blinks_briefly_and_hidden_pet_stops_timers(qtbot):
    controller = _Controller(_state())
    pet = MiniCountdownWidget(controller)
    qtbot.addWidget(pet)
    pet.set_motion_mode("standard")

    assert pet._blink_timer.isActive()
    pet._start_blink()
    assert pet._pet.blinking
    qtbot.wait(180)
    assert not pet._pet.blinking

    pet.hide()
    assert not pet._blink_timer.isActive()
    assert not pet._blink_close_timer.isActive()
    assert pet._fade_animation.state() == QAbstractAnimation.Stopped
    assert pet._mood_animation.state() == QAbstractAnimation.Stopped


def test_pet_applies_light_palette_and_uses_nine_point_hint(qtbot):
    pet = MiniCountdownWidget()
    qtbot.addWidget(pet)

    pet._apply_theme("light")

    assert pet.theme == "light"
    assert pet._pet._theme == "light"
    assert pet._hint_label.font().pointSize() == 9
    assert "#596981" in pet._hint_label.styleSheet()


def test_pet_preview_does_not_change_preferences_and_can_end_cleanly(qtbot):
    pet = MiniCountdownWidget()
    qtbot.addWidget(pet)

    pet.preview()

    assert pet.isVisible()
    assert pet._preview_timer.isActive()
    assert pet._label.text() == "倒计时桌宠预览"

    pet._finish_preview()

    assert not pet.isVisible()


def test_clearing_saved_position_moves_visible_pet_to_default(qtbot):
    screen = QApplication.primaryScreen()
    area = screen.availableGeometry()
    saved = QPoint(area.left() + 24, area.top() + 24)
    state = _state()
    state = replace(
        state,
        general=replace(state.general, pet_x=saved.x(), pet_y=saved.y()),
    )
    controller = _Controller(state)
    pet = MiniCountdownWidget(controller)
    qtbot.addWidget(pet)

    assert pet.pos() == saved

    controller.publish(
        replace(
            state,
            general=replace(state.general, pet_x=None, pet_y=None),
        )
    )

    assert pet.pos() == QPoint(
        area.right() - pet.width() - 18,
        area.bottom() - pet.height() - 18,
    )


def test_effective_break_suppression_hides_pet_and_stops_timers(qtbot):
    state = replace(
        _state(),
        effective_policy=EffectivePolicyState(
            breaks=FeatureRuntimeState(
                desired_enabled=True,
                effective_enabled=False,
                suppressed_by=("fullscreen",),
                resume_condition="退出全屏后恢复",
            )
        ),
    )
    controller = _Controller(state)
    pet = MiniCountdownWidget(controller)
    qtbot.addWidget(pet)

    assert not pet.isVisible()
    assert not pet._blink_timer.isActive()

    resumed = replace(
        _state(),
        effective_policy=EffectivePolicyState(
            breaks=FeatureRuntimeState(
                desired_enabled=True,
                effective_enabled=True,
            )
        ),
    )
    controller.publish(resumed)

    assert pet.isVisible()
    assert pet._blink_timer.isActive()


class _SignalRecorder:
    def __init__(self):
        self.values: list[bool] = []

    def emit(self, value: bool) -> None:
        self.values.append(value)


def test_app_poll_emits_when_system_motion_preference_changes(monkeypatch):
    recorder = _SignalRecorder()
    fake_app = type(
        "FakeApp",
        (),
        {
            "_theme": "dark",
            "_motion_enabled": True,
            "motion_changed": recorder,
        },
    )()
    monkeypatch.setattr(app_module, "client_area_animations_enabled", lambda: False)

    OpenCareEyesApp._poll_system_preferences(fake_app)

    assert fake_app._motion_enabled is False
    assert recorder.values == [False]
