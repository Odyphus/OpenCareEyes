from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QObject, Signal  # noqa: E402
from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QBoxLayout,
    QTabWidget,
    QWidget,
)

import opencareyes.ui.main_panel as main_panel_module  # noqa: E402
from opencareyes.ui.companion_pages import (  # noqa: E402
    AppPropRulesCard,
    CompanionAutomationPage,
    CompanionBreakPage,
    CompanionHomePage,
    FerretPreview,
    PetCatalogPage,
    StudyDeskPage,
)
from opencareyes.ui.onboarding import OnboardingDialog  # noqa: E402
from opencareyes.ui.tray_icon import TrayIcon  # noqa: E402


def _runtime(enabled=False):
    return SimpleNamespace(effective_enabled=enabled, suppressed_by=(), resume_condition='')


def _state():
    return SimpleNamespace(
        general=SimpleNamespace(
            theme='light',
            autostart=False,
            city='',
            latitude=None,
            longitude=None,
            location_configured=False,
        ),
        pet_catalog=SimpleNamespace(
            active_pet_id='snow_ferret',
            active_display_name='鼬鼬',
            available_pets=(
                SimpleNamespace(pet_id='snow_ferret', display_name='鼬鼬'),
                SimpleNamespace(pet_id='test_bird', display_name='小鸟'),
            ),
        ),
        companion=SimpleNamespace(
            enabled=True,
            behavior='idle',
            suppressed_by=(),
            scale_percent=100,
            follow_active_monitor=True,
            window_avoidance_enabled=True,
            sound_enabled=False,
            appearance=SimpleNamespace(
                headwear='',
                neckwear='red_scarf',
                bodywear='',
                held_item='',
                scene='',
                effect='',
            ),
        ),
        weather=SimpleNamespace(status='disabled'),
        quick_tools=SimpleNamespace(hourly_chime_enabled=False),
        context=SimpleNamespace(
            foreground_app_id='winword.exe',
            recent_app_id='winword.exe',
            session='active',
            fullscreen=False,
            notification_mode='normal',
            idle_seconds=0,
        ),
        effective_policy=SimpleNamespace(
            filter=_runtime(),
            dimmer=_runtime(),
            breaks=_runtime(True),
            focus=_runtime(),
        ),
        automation=SimpleNamespace(
            enabled=False,
            mode='fixed',
            on_time='19:00',
            off_time='07:30',
            days=(0, 1, 2, 3, 4),
            day_profile='office',
            night_profile='night',
            smart_pause=SimpleNamespace(
                enabled=True,
                fullscreen_enabled=True,
                natural_rest_enabled=True,
                app_rules=(),
            ),
        ),
        breaks=SimpleNamespace(
            enabled=True,
            paused=False,
            force_break=False,
            phase='working',
            remaining=1200,
            countdown_display='floating',
            reminder_style='progressive',
            rest_scene='gaze',
            cadence=SimpleNamespace(
                mode='20-20-20',
                short_interval=1200,
                short_duration=20,
                long_enabled=False,
                long_interval=3600,
                long_duration=300,
                short_remaining=1200,
                long_remaining=3600,
            ),
        ),
        display=SimpleNamespace(
            filter_enabled=False,
            dimmer_enabled=False,
            color_temperature=6500,
            dim_level=0,
            preset='office',
        ),
        focus=SimpleNamespace(enabled=False),
        global_pause=SimpleNamespace(active=False),
        capabilities=SimpleNamespace(automation_available=True),
    )


class _Controller(QObject):
    state_changed = Signal(object)
    operation_failed = Signal(str, str)
    notification_requested = Signal(str, str)
    break_tick = Signal(object)

    def __init__(self):
        super().__init__()
        self.state = _state()
        self.calls = []

    def __getattr__(self, name):
        def command(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return True

        return command


class _PreviewRepository(QObject):
    resource_ready = Signal(str, str)
    resource_failed = Signal(str, str)

    def __init__(self):
        super().__init__()
        self.frames = {}
        self.calls = []

    def load_frame(self, pet_id, resource_path):
        key = (str(pet_id), str(resource_path))
        self.calls.append(key)
        image = self.frames.get(key)
        return QImage(image) if isinstance(image, QImage) else None


def _app():
    return QApplication.instance() or QApplication([])


def test_companion_home_reflows_below_640_pixels():
    app = _app()
    page = CompanionHomePage(_Controller())
    page.resize(900, 600)
    page.show()
    app.processEvents()
    assert page._hero_layout.direction() == QBoxLayout.LeftToRight
    assert page._hero_layout.stretch(0) == 58

    page.resize(560, 500)
    app.processEvents()
    assert page._hero_layout.direction() == QBoxLayout.TopToBottom
    assert page.horizontalScrollBar().maximum() == 0
    page.close()


def test_preview_uses_repository_and_ignores_late_previous_pet():
    _app()
    repository = _PreviewRepository()
    preview = FerretPreview(asset_repository=repository)
    preview.set_preview('preview.png', '伙伴甲', pet_id='pet_a')
    preview.set_preview('preview.png', '伙伴乙', pet_id='pet_b')

    old = QImage(8, 8, QImage.Format_ARGB32_Premultiplied)
    old.fill(QColor('#FF0000'))
    repository.frames[('pet_a', 'preview.png')] = old
    repository.resource_ready.emit('pet_a', 'preview.png')
    assert preview._preview_image.isNull()

    current = QImage(8, 8, QImage.Format_ARGB32_Premultiplied)
    current.fill(QColor('#0000FF'))
    repository.frames[('pet_b', 'preview.png')] = current
    repository.resource_ready.emit('pet_b', 'preview.png')
    assert preview._preview_image.pixelColor(0, 0) == QColor('#0000FF')
    assert ('pet_b', 'preview.png') in repository.calls
    preview.close()


def test_catalog_render_is_differential_and_reflects_accessory_selection():
    controller = _Controller()
    page = PetCatalogPage(controller)
    assert page._pet_combo.count() == 2
    selected = page._accessory_buttons[('neckwear', 'red_scarf')]
    assert selected.isChecked()
    assert selected.objectName() == 'secondaryButton'
    assert '✓' in selected.text()
    assert '已佩戴' in selected.text()
    assert '已佩戴' in selected.accessibleName()
    assert page._countdown_display.currentData() == 'floating'
    assert not page.findChildren(AppPropRulesCard)
    assert controller.calls == []

    page.render(controller.state)
    assert controller.calls == []
    page._accessory_buttons[('neckwear', 'scarf')].click()
    assert controller.calls[-1][0] == 'set_pet_accessory'
    assert controller.calls[-1][1] == ('neckwear', 'scarf')


def test_catalog_reflows_controls_below_640_pixels():
    app = _app()
    page = PetCatalogPage(_Controller())
    page.resize(560, 640)
    page.show()
    app.processEvents()
    assert page._selector_layout.direction() == QBoxLayout.TopToBottom
    assert page._wardrobe_layout.direction() == QBoxLayout.TopToBottom
    assert page.horizontalScrollBar().maximum() == 0
    page.close()


def test_learning_desk_has_no_duplicate_overview_tab():
    page = StudyDeskPage(_Controller())
    tabs = page.findChild(QTabWidget)
    assert tabs is not None
    assert [tabs.tabText(index) for index in range(tabs.count())] == [
        '专注陪伴',
        '屏幕舒适',
    ]


def test_app_prop_rules_live_under_automation_and_break_page_is_focused():
    controller = _Controller()
    automation = CompanionAutomationPage(controller)
    app_props = automation.findChild(AppPropRulesCard)
    assert app_props is not None
    controller.state.context.foreground_app_id = r'C:\\Office\\WINWORD.EXE'
    app_props.render(controller.state)
    assert app_props._current_app_id == 'winword.exe'
    assert 'C:' not in app_props._app_label.text()

    rest = CompanionBreakPage(controller)
    hidden_titles = {
        label.text()
        for label in rest.findChildren(QWidget)
        if getattr(label, 'objectName', lambda: '')() == 'cardTitle'
        and label.parentWidget().isHidden()
    }
    assert {'桌面伙伴与倒计时', '高级设置'} <= hidden_titles
    assert rest._pet_card.isHidden()
    assert rest._advanced_card.isHidden()
    assert rest._force_toggle.parentWidget() is not rest._advanced_card


def test_main_panel_uses_top_navigation_and_overlay_toast(monkeypatch):
    app = _app()

    class Page(QWidget):
        def __init__(self, _controller):
            super().__init__()

    monkeypatch.setattr(main_panel_module, '_PAGES', (('陪伴屋', Page, 'missing.svg'),))
    panel = main_panel_module.MainPanel(_Controller())
    panel.resize(600, 420)
    panel.show()
    app.processEvents()
    assert panel._root_layout.direction() == QBoxLayout.TopToBottom
    assert panel._content_area.layout().indexOf(panel._message) == -1
    panel._show_error('test', '需要保留')
    assert panel._message.isVisible()
    assert not panel._message_timer.isActive()
    panel._message_close.click()
    assert not panel._message.isVisible()
    panel._show_notification('完成', '普通消息')
    assert panel._message_timer.isActive()
    panel.hide()


def test_main_panel_injects_shared_pet_assets_into_lazy_pet_pages():
    _app()
    repository = _PreviewRepository()
    panel = main_panel_module.MainPanel(
        _Controller(),
        asset_repository=repository,
    )

    assert panel._pages[0]._preview._asset_repository is repository
    catalog = panel._ensure_page(1)
    assert catalog._asset_repository is repository
    panel.close()



def test_onboarding_starts_with_the_companion_and_tray_is_grouped():
    controller = _Controller()
    dialog = OnboardingDialog(controller)
    assert dialog._stack.currentIndex() == 0
    assert dialog._pet_toggle.isChecked()
    assert '4' in dialog._step_label.text()

    panel = SimpleNamespace(show_page=lambda _name: None, show=lambda: None)
    tray = TrayIcon(controller, panel)
    top_level = [action.text() for action in tray._menu.actions() if not action.isSeparator()]
    assert '现在休息' in top_level
    assert '色温调节' not in top_level
    assert '屏幕舒适与专注' in top_level


def test_tray_opens_companion_bubble_with_keyboard_focus():
    controller = _Controller()
    panel = SimpleNamespace(show_page=lambda _name: None, show=lambda: None)
    requests = []
    runtime = SimpleNamespace(
        show_bubble=lambda **options: requests.append(options)
    )
    tray = TrayIcon(controller, panel, companion_runtime=runtime)

    assert tray._open_pet_bubble_action.isEnabled()
    tray._open_pet_bubble_action.trigger()

    assert requests == [{'focusable': True}]
