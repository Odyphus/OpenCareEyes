"""Exercise the public UI through real controller state and isolated settings."""
from __future__ import annotations

import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from opencareyes.config.settings import Settings  # noqa: E402
from opencareyes.constants import DIM_MAX  # noqa: E402
from opencareyes.controller import AppController  # noqa: E402
from opencareyes.core.break_reminder import BreakReminder  # noqa: E402
from opencareyes.ui.blue_light_page import BlueLightPage  # noqa: E402
from opencareyes.ui.automation_page import AutomationPage  # noqa: E402
from opencareyes.ui.companion_pages import CompanionHomePage, PetCatalogPage  # noqa: E402
from opencareyes.ui.focus_page import FocusPage  # noqa: E402
from opencareyes.ui.main_panel import MainPanel  # noqa: E402
from opencareyes.ui.settings_page import SettingsPage  # noqa: E402
from tests.test_controller import FakeCompanion, FakeDisplayEffect, FakeFocus, FakeHotkeys, MemoryStore  # noqa: E402


@pytest.fixture
def controller(qtbot):
    store = MemoryStore()
    settings = Settings(store)
    reminder = BreakReminder()
    hotkeys = FakeHotkeys()
    hotkeys.available = True
    instance = AppController(settings, FakeDisplayEffect(), FakeDisplayEffect(), reminder, FakeFocus(), companion=FakeCompanion(), hotkeys=hotkeys)
    yield instance, store
    reminder.stop()
    instance._pause_timer.stop()
    instance._focus_timer.stop()


@pytest.mark.parametrize('kind', ('temperature', 'dimmer', 'pet_scale', 'focus_dim'))
def test_keyboard_slider_changes_survive_settings_reload(qtbot, controller, kind):
    instance, store = controller
    if kind == 'pet_scale':
        page = PetCatalogPage(instance)
        page._behavior_section.set_expanded(True)
        slider = page._scale
    elif kind == 'focus_dim':
        page = FocusPage(instance)
        slider = page._dim_slider
    else:
        page = BlueLightPage(instance)
        slider = page._temperature_slider if kind == 'temperature' else page._dim_slider
    qtbot.addWidget(page)
    page.resize(760, 650)
    page.show()
    slider.setFocus()
    before = slider.value()
    QTest.keyClick(slider, Qt.Key_Left if before == slider.maximum() else Qt.Key_Right)
    assert slider.value() != before
    value = slider.value()
    persisted = Settings(store)
    if kind == 'temperature':
        assert persisted.color_temperature == value
        assert instance.state.display.color_temperature == value
    elif kind == 'dimmer':
        assert persisted.dim_level == round(value * DIM_MAX / 100)
    elif kind == 'pet_scale':
        assert persisted.pet_scale_percent == value
        assert instance.state.companion.scale_percent == value
    else:
        assert persisted.focus_dim_level == round(value * 255 / 100)


def test_home_can_enable_rest_and_pause_then_resume(qtbot, controller):
    instance, _store = controller
    instance.set_feature_enabled('breaks', False)
    page = CompanionHomePage(instance)
    qtbot.addWidget(page)
    page.show()
    assert page._rest_button.text() == '开启休息提醒'
    QTest.mouseClick(page._rest_button, Qt.LeftButton)
    assert instance.state.breaks.enabled
    assert page._rest_button.text() == '现在休息'
    QTest.mouseClick(page._rest_button, Qt.LeftButton)
    assert instance.state.breaks.phase == 'resting'
    assert page._rest_button.text() == '结束本次休息'
    QTest.mouseClick(page._rest_button, Qt.LeftButton)
    assert instance.state.breaks.phase == 'working'
    QTest.mouseClick(page._pause_button, Qt.LeftButton)
    assert instance.state.global_pause.active
    assert page._pause_button.text() == '恢复全部'
    QTest.mouseClick(page._pause_button, Qt.LeftButton)
    assert not instance.state.global_pause.active
    assert instance.state.breaks.enabled


def test_home_tick_updates_clock_without_reloading_pet(qtbot, controller, monkeypatch):
    instance, _store = controller
    instance.set_feature_enabled('breaks', True)
    page = CompanionHomePage(instance)
    qtbot.addWidget(page)
    def unexpected_reload(*args, **kwargs):
        raise AssertionError('A countdown tick must not reload the pet preview')
    monkeypatch.setattr(page._preview, 'set_preview', unexpected_reload)
    instance.break_tick.emit(59, 1200)
    assert '0:59' in page._next_break.text()
    monkeypatch.undo()
    instance.pause_all(minutes=30)
    instance.break_tick.emit(58, 1200)
    assert '暂停' in page._next_break.text()


def test_focus_primary_button_starts_and_ends_same_session(qtbot, controller):
    instance, _store = controller
    page = FocusPage(instance)
    qtbot.addWidget(page)
    page.show()
    QTest.mouseClick(page._start_button, Qt.LeftButton)
    assert instance.state.focus.enabled
    assert instance.state.focus.session_ends_at is not None
    assert page._start_button.text() == '结束专注'
    assert not page._duration_combo.isEnabled()
    QTest.mouseClick(page._start_button, Qt.LeftButton)
    assert not instance.state.focus.enabled
    assert instance.state.focus.session_ends_at is None
    assert page._start_button.text() == '开始专注'


def test_home_shortcuts_route_to_details_and_escape_dismisses_feedback_first(qtbot, controller):
    instance, _store = controller
    panel = MainPanel(instance)
    qtbot.addWidget(panel)
    panel._fit_available_geometry = lambda: None
    panel.show()
    home = panel._pages[0]
    home.page_requested.emit('屏幕舒适')
    assert panel._navigation.currentRow() == 2
    assert panel._stack.currentWidget().tabs.tabText(0) == '屏幕'
    panel._show_error('test', '测试错误提示')
    panel.activateWindow()
    panel.setFocus()
    qtbot.wait(20)
    QTest.keyClick(panel, Qt.Key_Escape)
    assert not panel._message.isVisible()
    assert panel.isVisible()
    QTest.keyClick(panel, Qt.Key_Escape)
    assert not panel.isVisible()


def test_settings_disclosure_is_keyboard_operable(qtbot, controller):
    instance, _store = controller
    page = SettingsPage(instance)
    qtbot.addWidget(page)
    page.show()
    section = page._hotkey_section
    assert section.contents.isHidden()
    section.toggle.setFocus()
    QTest.keyClick(section.toggle, Qt.Key_Space)
    assert section.contents.isVisible()
    assert '收起' in section.toggle.accessibleName()
    QTest.keyClick(section.toggle, Qt.Key_Space)
    assert section.contents.isHidden()


def test_unsaved_hotkeys_survive_other_setting_changes(qtbot, controller):
    instance, store = controller
    page = SettingsPage(instance)
    qtbot.addWidget(page)
    page.show()
    page._hotkey_section.set_expanded(True)
    edit = page._hotkey_edits['filter']
    edit.setKeySequence('Ctrl+Shift+9')
    page._theme_combo.setFocus()
    instance.set_theme('dark')
    assert edit.keySequence().toString() == 'Ctrl+Shift+9'
    assert '尚未保存' in page._hotkey_notice.text()
    assert page._save_hotkeys_button.isEnabled()
    page.ensureWidgetVisible(page._save_hotkeys_button, 0, 16)
    page._save_hotkeys_button.setFocus()
    qtbot.wait(20)
    QTest.keyClick(page._save_hotkeys_button, Qt.Key_Space)
    assert Settings(store).hotkey_filter == 'ctrl+shift+9'
    assert '已保存' in page._hotkey_notice.text()


def test_automation_settings_fit_the_narrow_window_without_horizontal_clipping(qtbot, controller):
    instance, _store = controller
    page = AutomationPage(instance)
    qtbot.addWidget(page)
    page.resize(448, 520)
    page.show()
    qtbot.waitUntil(lambda: page.content.width() <= page.viewport().width())
    assert page._rules_table.columnCount() == 6


@pytest.mark.parametrize('theme', ('light', 'dark'))
@pytest.mark.parametrize('width', (480, 560, 760, 980))
def test_compact_navigation_keeps_every_destination_visible(qtbot, controller, theme, width):
    from pathlib import Path
    from PySide6.QtWidgets import QApplication, QStyle, QStyleOptionViewItem

    app = QApplication.instance()
    previous = app.styleSheet()
    instance, _store = controller
    panel = MainPanel(instance)
    qtbot.addWidget(panel)
    panel._fit_available_geometry = lambda: None
    try:
        style_path = Path(__file__).resolve().parents[1] / f'assets/styles/{theme}.qss'
        app.setStyleSheet(style_path.read_text(encoding='utf-8'))
        panel.resize(width, 520)
        panel.show()
        qtbot.wait(30)
        navigation = panel._navigation
        assert navigation.horizontalScrollBar().maximum() == 0
        for index in range(navigation.count()):
            rect = navigation.visualItemRect(navigation.item(index))
            assert rect.left() >= 0
            assert rect.right() < navigation.viewport().width()
            option = QStyleOptionViewItem()
            navigation.initViewItemOption(option)
            navigation.itemDelegate().initStyleOption(option, navigation.model().index(index, 0))
            option.rect = rect
            text_rect = navigation.style().subElementRect(QStyle.SE_ItemViewItemText, option, navigation)
            assert option.fontMetrics.horizontalAdvance(option.text) <= text_rect.width()
    finally:
        app.setStyleSheet(previous)
