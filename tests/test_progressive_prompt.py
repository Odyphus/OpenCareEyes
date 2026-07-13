"""Progressive, non-blocking break prompt tests."""

from types import SimpleNamespace

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtTest import QSignalSpy

from opencareyes.ui.break_prompt import BreakPrompt
from opencareyes.ui.break_page import BreakPage
from opencareyes.ui.mini_countdown import MiniCountdownWidget


class _Controller(QObject):
    state_changed = Signal(object)
    break_tick = Signal(int, int)

    def __init__(self, state):
        super().__init__()
        self.state = state
        self.started = 0
        self.snoozed: list[int] = []
        self.undo_count = 0
        self.skipped = 0
        self.positions: list[tuple[int, int]] = []
        self.reset_count = 0
        self.display_modes: list[str] = []

    def start_due_break(self):
        self.started += 1

    def snooze_break(self, minutes):
        self.snoozed.append(minutes)

    def undo_break_snooze(self):
        self.undo_count += 1

    def skip_break(self):
        self.skipped += 1

    def set_pet_position(self, x, y):
        self.positions.append((x, y))

    def reset_pet_position(self):
        self.reset_count += 1

    def set_break_countdown_display(self, mode):
        self.display_modes.append(mode)


def _state(
    *,
    stage="gentle",
    force=False,
    suppressed=(),
    phase="prompting",
    display="tray",
    remaining=0,
):
    return SimpleNamespace(
        breaks=SimpleNamespace(
            enabled=True,
            phase=phase,
            force_break=force,
            reminder_style="progressive",
            due_kind="short",
            prompt_stage=stage,
            countdown_display=display,
            paused=False,
            remaining=remaining,
        ),
        effective_policy=SimpleNamespace(
            breaks=SimpleNamespace(suppressed_by=suppressed)
        ),
    )


def test_prompt_shows_without_requesting_focus_and_starts_on_accept(qtbot):
    controller = _Controller(_state())
    prompt = BreakPrompt(controller)
    qtbot.addWidget(prompt)

    assert prompt.isVisible()
    assert prompt.testAttribute(Qt.WA_ShowWithoutActivating)
    assert prompt.stage == "gentle"
    assert controller.started == 0

    qtbot.mouseClick(prompt._start, Qt.LeftButton)
    assert controller.started == 1
    assert not prompt.isVisible()


def test_prompt_supports_all_snooze_choices_and_skip(qtbot):
    prompt = BreakPrompt()
    qtbot.addWidget(prompt)
    snoozed = QSignalSpy(prompt.snooze_requested)
    skipped = QSignalSpy(prompt.skip_requested)

    prompt.show_prompt()
    prompt._snooze(10)
    assert snoozed.at(0) == [10]

    prompt.show_prompt()
    qtbot.mouseClick(prompt._skip, Qt.LeftButton)
    assert skipped.count() == 1


def test_escape_is_a_five_minute_snooze(qtbot):
    prompt = BreakPrompt()
    qtbot.addWidget(prompt)
    snoozed = QSignalSpy(prompt.snooze_requested)
    prompt.show_prompt()

    qtbot.keyClick(prompt, Qt.Key_Escape)

    assert snoozed.at(0) == [5]
    assert not prompt.isVisible()


def test_five_minute_snooze_offers_separate_nonblocking_undo(qtbot):
    controller = _Controller(_state())
    prompt = BreakPrompt(controller)
    qtbot.addWidget(prompt)

    prompt._snooze(5)

    assert not prompt.isVisible()
    assert prompt._undo_toast.isVisible()
    qtbot.mouseClick(prompt._undo_toast._undo, Qt.LeftButton)
    assert controller.undo_count == 1
    assert not prompt._undo_toast.isVisible()


def test_prompt_escalates_visually_but_remains_non_blocking(qtbot):
    controller = _Controller(_state(stage="gentle"))
    prompt = BreakPrompt(controller)
    qtbot.addWidget(prompt)
    gentle_size = prompt.size()

    controller.state = _state(stage="prominent")
    controller.state_changed.emit(controller.state)

    assert prompt.stage == "prominent"
    assert prompt.size().width() > gentle_size.width()
    assert prompt.windowFlags() & Qt.Tool


def test_strict_or_suppressed_prompt_is_hidden(qtbot):
    controller = _Controller(_state(force=True))
    prompt = BreakPrompt(controller)
    qtbot.addWidget(prompt)
    assert not prompt.isVisible()

    controller.state = _state(suppressed=("fullscreen",))
    controller.state_changed.emit(controller.state)
    assert not prompt.isVisible()


def test_floating_pet_expands_into_due_break_actions(qtbot):
    controller = _Controller(_state(display="floating"))
    pet = MiniCountdownWidget(controller)
    qtbot.addWidget(pet)

    assert pet.isVisible()
    assert pet._prompt_expanded
    assert pet.mood == "due"
    assert pet._start_button.isVisible()
    assert pet.testAttribute(Qt.WA_ShowWithoutActivating)
    assert set(pet._snooze_actions) == {5, 10, 30}

    pet._snooze_actions[10].trigger()
    assert controller.snoozed == [10]
    assert not pet._prompt_expanded
    assert pet._undo_bar.isVisible()
    assert pet._undo_timer.interval() == 8000
    assert pet._undo_timer.isActive()


def test_pet_all_snooze_choices_emit_exact_minutes(qtbot):
    pet = MiniCountdownWidget()
    qtbot.addWidget(pet)
    snoozed = QSignalSpy(pet.snooze_requested)

    for minutes in (5, 10, 30):
        pet.expand_prompt()
        pet._snooze_actions[minutes].trigger()

    assert [snoozed.at(index) for index in range(snoozed.count())] == [
        [5],
        [10],
        [30],
    ]


def test_pet_expanded_close_snoozes_and_undoes_without_hiding(qtbot):
    controller = _Controller(_state(display="floating"))
    pet = MiniCountdownWidget(controller)
    qtbot.addWidget(pet)

    qtbot.mouseClick(pet._close_button, Qt.LeftButton)

    assert controller.snoozed == [5]
    assert controller.display_modes == []
    assert pet.isVisible()
    assert not pet._prompt_expanded
    assert pet._undo_bar.isVisible()

    qtbot.mouseClick(pet._undo_button, Qt.LeftButton)
    assert controller.undo_count == 1
    assert not pet._undo_bar.isVisible()


def test_pet_expanded_escape_is_a_five_minute_snooze(qtbot):
    controller = _Controller(_state(display="floating"))
    pet = MiniCountdownWidget(controller)
    qtbot.addWidget(pet)

    qtbot.keyClick(pet, Qt.Key_Escape)

    assert controller.snoozed == [5]
    assert pet.isVisible()
    assert not pet._prompt_expanded
    assert pet._undo_bar.isVisible()


def test_pet_accepts_tick_updates_and_exposes_position_hooks(qtbot):
    controller = _Controller(
        _state(stage="none", phase="working", display="floating", remaining=83)
    )
    pet = MiniCountdownWidget(controller)
    qtbot.addWidget(pet)
    assert pet._countdown_label.text() == "1:23"

    controller.break_tick.emit(42, 1200)
    assert pet._countdown_label.text() == "0:42"

    pet.position_changed.emit(120, 240)
    assert controller.positions == [(120, 240)]
    pet.reset_position()
    assert controller.reset_count == 1


class _PageController(_Controller):
    def __init__(self, state):
        super().__init__(state)
        self.modes: list[str] = []
        self.cadences: list[tuple] = []
        self.styles: list[str] = []

    def set_feature_enabled(self, *_args):
        return True

    def pause_break(self):
        return True

    def resume_break(self):
        return True

    def set_break_mode(self, mode):
        self.modes.append(mode)

    def set_break_cadence(self, *values):
        self.cadences.append(values)

    def set_force_break(self, _enabled):
        return True

    def set_break_reminder_style(self, style):
        self.styles.append(style)


def _page_state():
    state = _state(stage="none", phase="working", remaining=1200)
    state.breaks.mode = "custom"
    state.breaks.work_duration = 1200
    state.breaks.break_duration = 20
    state.breaks.long_enabled = True
    state.breaks.long_interval = 3600
    state.breaks.long_duration = 300
    state.breaks.short_remaining = 1200
    state.breaks.long_remaining = 3600
    state.capabilities = SimpleNamespace(breaks_available=True)
    return state


def test_break_page_exposes_balanced_custom_and_progressive_controls(qtbot):
    controller = _PageController(_page_state())
    page = BreakPage(controller)
    qtbot.addWidget(page)

    assert page._mode_combo.findData("balanced") >= 0
    assert page._reminder_style_combo.findData("progressive") >= 0
    assert page._long_toggle.isChecked()
    assert page._long_interval_spin.value() == 60

    page._work_spin.setValue(30)
    page._break_spin.setValue(45)
    page._long_interval_spin.setValue(90)
    page._long_duration_spin.setValue(8)
    controller.cadences.clear()
    page._durations_changed()

    assert controller.cadences[-1] == (1800, 45, True, 5400, 480)


def test_break_page_pet_and_reminder_actions_use_controller_hooks(qtbot):
    controller = _PageController(_page_state())
    page = BreakPage(controller)
    qtbot.addWidget(page)

    fullscreen = page._reminder_style_combo.findData("fullscreen")
    page._reminder_style_combo.setCurrentIndex(fullscreen)
    assert controller.styles == ["fullscreen"]

    qtbot.mouseClick(page._pet_preview_button, Qt.LeftButton)
    qtbot.mouseClick(page._pet_reset_button, Qt.LeftButton)
    assert controller.display_modes == ["floating"]
    assert controller.reset_count == 1
