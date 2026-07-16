'''Tests for the independent non-blocking companion bubble.'''

from PySide6.QtCore import QPoint, QRect, QTimer, Qt
from PySide6.QtTest import QSignalSpy

from opencareyes.ui.pet_bubble import PetBubble


def test_bubble_has_quick_tools_and_no_private_countdown_timer(qtbot):
    bubble = PetBubble()
    qtbot.addWidget(bubble)
    requested = QSignalSpy(bubble.tool_requested)

    assert bubble.windowFlags() & Qt.Tool
    assert bubble.testAttribute(Qt.WA_ShowWithoutActivating)
    assert set(bubble.tool_buttons) == {'rest', 'timer', 'note', 'status'}
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
