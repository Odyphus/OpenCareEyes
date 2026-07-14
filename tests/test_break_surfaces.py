"""Regression tests for the full-screen reminder and countdown pet."""

from dataclasses import replace

from PySide6.QtCore import QObject, Qt, Signal

from opencareyes.state import AppState, BreakState
from opencareyes.ui.break_overlay import BreakOverlay
from opencareyes.ui.mini_countdown import MiniCountdownWidget


class _Controller(QObject):
    state_changed = Signal(object)
    break_tick = Signal(int, int)

    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self.skip_calls = 0
        self.snooze_calls: list[int] = []
        self.display_modes: list[str] = []

    def publish(self, state: AppState) -> None:
        self.state = state
        self.state_changed.emit(state)

    def skip_break(self) -> bool:
        self.skip_calls += 1
        self.publish(
            replace(
                self.state,
                breaks=replace(self.state.breaks, phase="working"),
            )
        )
        return True

    def snooze_break(self, minutes: int = 5) -> bool:
        self.snooze_calls.append(minutes)
        return True

    def set_break_countdown_display(self, mode: str) -> bool:
        self.display_modes.append(mode)
        self.publish(
            replace(
                self.state,
                breaks=replace(self.state.breaks, countdown_display=mode),
            )
        )
        return True


def _state(
    *,
    phase: str = "working",
    force: bool = False,
    display: str = "tray",
    paused: bool = False,
    remaining: int = 83,
) -> AppState:
    return AppState(
        breaks=BreakState(
            enabled=True,
            phase=phase,
            remaining=remaining,
            total=1200,
            force_break=force,
            countdown_display=display,
            paused=paused,
        )
    )


def test_every_rest_phase_shows_topmost_overlay(qtbot):
    controller = _Controller(_state(phase="resting", force=False))
    overlay = BreakOverlay(controller)
    qtbot.addWidget(overlay)

    assert overlay.isVisible()
    assert overlay.windowFlags() & Qt.WindowStaysOnTopHint
    assert overlay._snooze_button.isVisible()
    assert overlay._skip_button.isVisible()


def test_strict_rest_hides_snooze_but_keeps_safe_exit(qtbot):
    controller = _Controller(_state(phase="resting", force=True))
    overlay = BreakOverlay(controller)
    qtbot.addWidget(overlay)

    assert overlay.isVisible()
    assert not overlay._snooze_button.isVisible()
    assert overlay._skip_button.isVisible()
    assert overlay._skip_button.text() == "安全结束本次休息"

    qtbot.keyClick(overlay, Qt.Key_Escape)
    assert controller.skip_calls == 1
    assert not overlay.isVisible()


def test_overlay_hides_when_work_resumes(qtbot):
    controller = _Controller(_state(phase="resting"))
    overlay = BreakOverlay(controller)
    qtbot.addWidget(overlay)
    assert overlay.isVisible()

    controller.publish(_state(phase="working"))
    assert not overlay.isVisible()


def test_visible_overlay_does_not_repeat_unchanged_screen_geometry(
    qtbot,
    monkeypatch,
):
    controller = _Controller(_state(phase="resting"))
    overlay = BreakOverlay(controller)
    qtbot.addWidget(overlay)
    geometry_calls = []
    monkeypatch.setattr(
        overlay,
        "setGeometry",
        lambda *args: geometry_calls.append(args),
    )

    controller.publish(_state(phase="resting", remaining=42))

    assert geometry_calls == []


def test_break_tick_only_updates_countdown_text(qtbot, monkeypatch):
    controller = _Controller(_state(phase="resting", remaining=20))
    overlay = BreakOverlay(controller)
    qtbot.addWidget(overlay)
    window_calls = []
    for method_name in ("show", "hide", "raise_", "activateWindow", "setGeometry"):
        monkeypatch.setattr(
            overlay,
            method_name,
            lambda *args, name=method_name: window_calls.append(name),
        )

    for remaining in range(20, -1, -1):
        controller.break_tick.emit(remaining, 20)
        assert overlay._countdown_label.text() == f"0:{remaining:02d}"
        assert overlay.isVisible()

    assert window_calls == []


def test_skip_button_ends_rest_once_and_hides_immediately(qtbot):
    controller = _Controller(_state(phase="resting"))
    overlay = BreakOverlay(controller)
    qtbot.addWidget(overlay)

    qtbot.mouseClick(overlay._skip_button, Qt.LeftButton)

    assert controller.skip_calls == 1
    assert controller.state.breaks.phase == "working"
    assert not overlay.isVisible()


def test_countdown_pet_shows_state_and_can_be_closed(qtbot):
    controller = _Controller(_state(display="floating", remaining=83))
    pet = MiniCountdownWidget(controller)
    qtbot.addWidget(pet)

    assert pet.isVisible()
    assert pet.windowFlags() & Qt.WindowStaysOnTopHint
    assert pet.mood == "working"
    assert pet._countdown_label.text() == "1:23"

    qtbot.mouseClick(pet._close_button, Qt.LeftButton)
    assert controller.display_modes == ["tray"]
    assert not pet.isVisible()


def test_countdown_pet_reflects_rest_and_pause(qtbot):
    controller = _Controller(_state(phase="resting", display="floating"))
    pet = MiniCountdownWidget(controller)
    qtbot.addWidget(pet)

    assert pet.mood == "resting"
    assert pet._label.text() == "休息时间"

    controller.publish(
        _state(phase="working", display="floating", paused=True, remaining=42)
    )
    assert pet.mood == "paused"
    assert pet._label.text() == "计时已暂停"
    assert pet._countdown_label.text() == "0:42"

    controller.publish(
        _state(phase="resting", display="floating", paused=True, remaining=21)
    )
    assert pet.mood == "paused"
    assert pet._label.text() == "休息已暂停"
    assert pet._countdown_label.text() == "0:21"


def test_standalone_overlay_escape_is_always_safe(qtbot):
    overlay = BreakOverlay()
    qtbot.addWidget(overlay)
    overlay.start_break(20, force=True)
    assert overlay.isVisible()

    qtbot.keyClick(overlay, Qt.Key_Escape)
    assert not overlay.isVisible()
