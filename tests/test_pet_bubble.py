'''Tests for the independent non-blocking companion bubble.'''

from types import SimpleNamespace

from PySide6.QtCore import QPoint, QRect, QTimer, Qt
from PySide6.QtGui import QPalette
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from opencareyes.ui.pet_bubble import PetBubble


def test_bubble_has_quick_tools_and_no_private_countdown_timer(qtbot):
    bubble = PetBubble()
    qtbot.addWidget(bubble)
    requested = QSignalSpy(bubble.tool_requested)

    assert bubble.windowFlags() & Qt.Tool
    assert bubble.testAttribute(Qt.WA_ShowWithoutActivating)
    assert set(bubble.tool_buttons) == {'rest', 'timer', 'note', 'status'}
    assert bubble.mode == 'quick'
    assert not bubble._tools_widget.isHidden()
    assert bubble._rest_actions_widget.isHidden()
    assert bubble.findChildren(QTimer) == []

    qtbot.mouseClick(bubble.tool_buttons['timer'], Qt.LeftButton)
    assert requested.at(0) == ['timer']


def test_break_tick_only_changes_text(qtbot):
    bubble = PetBubble()
    qtbot.addWidget(bubble)
    original_position = QPoint(bubble.pos())

    bubble.set_break_countdown(83, 1200)
    assert bubble._countdown.text() == '1:23'
    assert bubble.pos() == original_position

    bubble.set_break_countdown(0)
    assert bubble._countdown.text() == '0:00'


def test_show_for_keeps_bubble_on_current_screen_and_escape_hides(qtbot):
    bubble = PetBubble()
    qtbot.addWidget(bubble)
    dismissed = QSignalSpy(bubble.dismissed)

    bubble.show_for(QRect(40, 40, 96, 112))
    assert bubble.isVisible()
    screen = bubble.screen()
    assert screen.availableGeometry().contains(bubble.geometry())

    qtbot.keyClick(bubble, Qt.Key_Escape)
    assert not bubble.isVisible()
    assert dismissed.count() == 1


def test_focusable_entry_activates_first_action_but_mouse_entry_does_not(qtbot):
    bubble = PetBubble()
    qtbot.addWidget(bubble)
    anchor = QRect(40, 40, 96, 112)

    bubble.show_for(anchor)
    assert bubble.testAttribute(Qt.WA_ShowWithoutActivating)
    bubble.hide()

    bubble.toggle_for(anchor, focusable=True)
    assert not bubble.testAttribute(Qt.WA_ShowWithoutActivating)
    qtbot.waitUntil(lambda: bubble.tool_buttons['rest'].hasFocus())


def test_rest_prompt_mode_exposes_due_break_actions(qtbot):
    bubble = PetBubble()
    qtbot.addWidget(bubble)
    started = QSignalSpy(bubble.start_due_requested)
    snoozed = QSignalSpy(bubble.snooze_requested)
    skipped = QSignalSpy(bubble.skip_requested)

    bubble.show_rest_prompt(QRect(40, 40, 96, 112))

    assert bubble.isVisible()
    assert bubble.mode == 'rest_prompt'
    assert bubble.is_rest_prompt_active
    assert not bubble._tools_widget.isVisible()
    assert bubble._rest_actions_widget.isVisible()
    assert set(bubble._snooze_actions) == {5, 10, 30}

    bubble.set_status('普通状态', '不应覆盖休息提醒')
    assert bubble._title.text() == '该休息一下眼睛了'

    qtbot.mouseClick(bubble._start_due_button, Qt.LeftButton)
    assert started.count() == 1
    assert not bubble.isVisible()
    assert bubble.mode == 'quick'

    bubble.show_rest_prompt(QRect(40, 40, 96, 112))
    bubble._snooze_actions[30].trigger()
    assert snoozed.at(0) == [30]
    assert not bubble.isVisible()

    bubble.show_rest_prompt(QRect(40, 40, 96, 112))
    qtbot.mouseClick(bubble._skip_button, Qt.LeftButton)
    assert skipped.count() == 1
    assert not bubble.isVisible()


def test_rest_prompt_escape_snoozes_five_minutes(qtbot):
    bubble = PetBubble()
    qtbot.addWidget(bubble)
    snoozed = QSignalSpy(bubble.snooze_requested)

    bubble.show_rest_prompt(QRect(40, 40, 96, 112))
    qtbot.keyClick(bubble, Qt.Key_Escape)

    assert snoozed.at(0) == [5]
    assert not bubble.isVisible()


def test_rest_prompt_close_and_toggle_snooze_instead_of_silent_hide(qtbot):
    bubble = PetBubble()
    qtbot.addWidget(bubble)
    snoozed = QSignalSpy(bubble.snooze_requested)
    anchor = QRect(40, 40, 96, 112)

    bubble.show_rest_prompt(anchor)
    qtbot.mouseClick(bubble._close, Qt.LeftButton)
    assert snoozed.at(0) == [5]
    assert bubble.mode == 'quick'

    bubble.show_rest_prompt(anchor)
    bubble.toggle_for(anchor)
    assert snoozed.at(1) == [5]
    assert not bubble.isVisible()


def test_bubble_apply_theme_alias_supports_light_dark_and_high_contrast(qtbot):
    bubble = PetBubble()
    qtbot.addWidget(bubble)

    bubble.apply_theme(SimpleNamespace(resolved='light', high_contrast=False))
    assert bubble.theme == 'light'
    assert bubble._active_palette['card'] == '#F8FBFF'

    bubble.apply_theme(SimpleNamespace(resolved='dark', high_contrast=False))
    assert bubble.theme == 'dark'
    assert bubble._active_palette['card'] == '#151C29'

    bubble.apply_theme(SimpleNamespace(resolved='dark', high_contrast=True))
    native = QApplication.palette()
    assert bubble._high_contrast is True
    assert bubble._active_palette['card'] == native.color(QPalette.Window).name()
    for button in (
        bubble._close,
        bubble._start_due_button,
        bubble._snooze_button,
        bubble._skip_button,
    ):
        assert button.focusPolicy() == Qt.StrongFocus
        assert button.accessibleName()
