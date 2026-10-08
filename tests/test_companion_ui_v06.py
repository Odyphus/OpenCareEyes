from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest  # noqa: E402
from PySide6.QtCore import QObject, Qt, Signal  # noqa: E402
from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QBoxLayout,
    QTabWidget,
    QWidget,
)
from PySide6.QtTest import QTest  # noqa: E402

import opencareyes.ui.main_panel as main_panel_module  # noqa: E402
from opencareyes.ui.companion_pages import (  # noqa: E402
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
        pet_wardrobe=SimpleNamespace(
            available_outfits=(
                SimpleNamespace(
                    outfit_id='snow_slope_skier',
                    display_name='雪坡滑雪客',
                    description='薄荷绿滑雪外套与浅蓝色护目镜。',
                    thumbnail_path='outfits/snow_slope_skier/thumbnail.png',
                    preview_path='outfits/snow_slope_skier/preview.png',
                    available=True,
                ),
                SimpleNamespace(
                    outfit_id='thunder_mage',
                    display_name='雷系小巫师',
                    description='紫黑镶金斗篷与星光法杖。',
                    thumbnail_path='outfits/thunder_mage/thumbnail.png',
                    preview_path='outfits/thunder_mage/preview.png',
                    available=True,
                ),
                SimpleNamespace(
                    outfit_id='missing_outfit',
                    display_name='资源缺失造型',
                    description='用于验证不可用状态。',
                    thumbnail_path='outfits/missing/thumbnail.png',
                    preview_path='outfits/missing/preview.png',
                    available=False,
                ),
            ),
            mode='outfit',
            selected_outfit_id='snow_slope_skier',
            effective_outfit_id='snow_slope_skier',
            loading_outfit_id='',
            error='',
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
                neckwear='',
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
    wardrobe_changed = Signal(object)
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


def test_catalog_render_is_differential_and_has_no_legacy_accessory_controls():
    controller = _Controller()
    page = PetCatalogPage(controller)
    assert page._pet_combo.count() == 2
    assert not hasattr(page, '_accessory_buttons')
    assert not hasattr(page, '_advanced_accessories_toggle')
    assert page._countdown_display.currentData() == 'floating'
    assert controller.calls == []

    page.render(controller.state)
    assert controller.calls == []


def test_catalog_empty_loading_state_uses_active_pet_without_species_hard_coding():
    _app()
    controller = _Controller()
    controller.state.pet_catalog.available_pets = ()
    controller.state.pet_catalog.active_pet_id = 'tiny_bird'
    controller.state.pet_wardrobe.available_outfits = ()

    page = PetCatalogPage(controller)

    assert page._pet_combo.count() == 1
    assert page._pet_combo.itemData(0) == 'tiny_bird'
    assert page._pet_combo.itemText(0) == 'tiny bird'
    assert '白鼬' not in page._pet_combo.itemText(0)
    assert not page._wardrobe_empty.isHidden()
    assert page._wardrobe_view.isHidden()
    assert page._wardrobe_columns == 0
    assert not page._wear_outfit.isEnabled()
    assert page._wardrobe_detail_title.text() == '暂无整套造型'
    page.close()


@pytest.mark.parametrize('activation_key', (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space))
def test_wardrobe_is_manifest_driven_and_only_explicit_activation_wears_outfit(
    activation_key,
):
    app = _app()
    controller = _Controller()
    page = PetCatalogPage(controller)

    assert page.layout.indexOf(page._wardrobe_card) == 1
    assert page._wardrobe_model.rowCount() == 3
    assert page._wardrobe_status.text() == '已锁定：雪坡滑雪客'
    assert page._wardrobe_detail_title.text() == '雪坡滑雪客'
    assert '已穿戴' in page._wardrobe_model.index(0, 0).data(Qt.AccessibleTextRole)
    assert '资源不可用' in page._wardrobe_model.index(2, 0).data(
        Qt.AccessibleDescriptionRole
    )

    controller.calls.clear()
    page._wardrobe_view.setCurrentIndex(page._wardrobe_model.index(1, 0))
    app.processEvents()
    assert controller.calls == []
    assert page._wardrobe_detail_title.text() == '雷系小巫师'

    QTest.keyClick(page._wardrobe_view, activation_key)
    assert controller.calls[-1] == ('set_pet_outfit', ('thunder_mage',), {})

    page._restore_outfit.click()
    assert controller.calls[-1] == ('set_pet_outfit', (None,), {})
    page.close()


def test_wardrobe_double_click_wears_the_clicked_outfit():
    app = _app()
    controller = _Controller()
    page = PetCatalogPage(controller)
    page.resize(900, 700)
    page.show()
    app.processEvents()

    index = page._wardrobe_model.index(1, 0)
    target = page._wardrobe_view.visualRect(index)
    assert target.isValid() and not target.isEmpty()
    controller.calls.clear()
    QTest.mouseDClick(
        page._wardrobe_view.viewport(),
        Qt.LeftButton,
        Qt.NoModifier,
        target.center(),
    )
    app.processEvents()

    assert controller.calls[-1] == ('set_pet_outfit', ('thunder_mage',), {})
    page.close()


def test_wardrobe_lightweight_loading_signal_updates_only_wardrobe_controls():
    app = _app()
    controller = _Controller()
    page = PetCatalogPage(controller)
    original_personality = page._personality.text()
    loading = SimpleNamespace(
        available_outfits=controller.state.pet_wardrobe.available_outfits,
        mode='outfit',
        selected_outfit_id='snow_slope_skier',
        effective_outfit_id='snow_slope_skier',
        loading_outfit_id='thunder_mage',
        error='',
    )

    controller.wardrobe_changed.emit(loading)
    app.processEvents()

    assert page._wardrobe_status.text() == '正在穿戴：雷系小巫师'
    assert page._loading_outfit_id == 'thunder_mage'
    assert not page._wear_outfit.isEnabled()
    assert not page._restore_outfit.isEnabled()
    assert page._personality.text() == original_personality
    assert page._wardrobe_model.index(1, 0).data(
        page._wardrobe_model.LoadingRole
    )

    controller.calls.clear()
    page._wardrobe_view.setCurrentIndex(page._wardrobe_model.index(1, 0))
    QTest.keyClick(page._wardrobe_view, Qt.Key_Return)
    assert controller.calls == []
    page.close()


def test_wardrobe_lightweight_failure_keeps_current_outfit_and_exposes_error():
    app = _app()
    controller = _Controller()
    page = PetCatalogPage(controller)
    failed = SimpleNamespace(
        available_outfits=controller.state.pet_wardrobe.available_outfits,
        mode='outfit',
        selected_outfit_id='snow_slope_skier',
        effective_outfit_id='snow_slope_skier',
        loading_outfit_id='',
        error='雷系小巫师资源预加载失败，已保留当前造型。',
    )

    controller.wardrobe_changed.emit(failed)
    app.processEvents()

    assert page._wardrobe_status.text() == '已锁定：雪坡滑雪客'
    assert page._wardrobe_model.index(0, 0).data(
        page._wardrobe_model.EffectiveRole
    )
    assert not page._wardrobe_error.isHidden()
    assert '已保留当前造型' in page._wardrobe_error.text()
    assert '已保留当前造型' in page._wardrobe_status.accessibleDescription()
    assert page._restore_outfit.isEnabled()
    assert controller.calls == []
    page.close()


def test_wardrobe_loads_selected_detail_then_visible_card_thumbnails_lazily():
    app = _app()
    repository = _PreviewRepository()
    page = PetCatalogPage(_Controller(), asset_repository=repository)
    assert len(repository.calls) == 1

    page.resize(900, 700)
    page.show()
    app.processEvents()
    assert 0 < len(repository.calls) <= page._wardrobe_model.rowCount()
    assert all(pet_id == 'snow_ferret' for pet_id, _path in repository.calls)
    page.close()


def test_catalog_reflows_controls_below_640_pixels():
    app = _app()
    page = PetCatalogPage(_Controller())
    page.resize(560, 640)
    page.show()
    app.processEvents()
    assert page._selector_layout.direction() == QBoxLayout.TopToBottom
    assert page._wardrobe_content_layout.direction() == QBoxLayout.TopToBottom
    assert page._wardrobe_action_layout.direction() == QBoxLayout.TopToBottom
    assert page._wardrobe_columns == 2
    assert page.horizontalScrollBar().maximum() == 0
    page.close()


def test_catalog_uses_compact_layout_at_480_pixels():
    app = _app()
    page = PetCatalogPage(_Controller())
    page.resize(480, 640)
    page.show()
    app.processEvents()

    assert page._wardrobe_content_layout.direction() == QBoxLayout.TopToBottom
    assert page._wardrobe_columns == 2
    assert (
        page._wardrobe_content_layout.indexOf(page._wardrobe_detail_panel)
        < page._wardrobe_content_layout.indexOf(page._wardrobe_gallery)
    )
    assert page.horizontalScrollBar().maximum() == 0
    page.close()


def test_catalog_render_restores_guard_after_exception(monkeypatch):
    _app()
    page = PetCatalogPage(_Controller())

    def fail(_state):
        raise RuntimeError('render failed')

    monkeypatch.setattr(page, '_render_state', fail)
    with pytest.raises(RuntimeError, match='render failed'):
        page.render(page._controller.state)

    assert not page._rendering
    page.close()


def test_wardrobe_without_asset_repository_reports_preview_unavailable():
    _app()
    page = PetCatalogPage(_Controller())
    index = page._wardrobe_model.index(0, 0)

    assert page._wardrobe_model.thumbnail(index).isNull()
    assert page._wardrobe_model.thumbnail_placeholder(index) == '资源不可用'
    page.close()


def test_learning_desk_has_no_duplicate_overview_tab():
    page = StudyDeskPage(_Controller())
    tabs = page.findChild(QTabWidget)
    assert tabs is not None
    assert [tabs.tabText(index) for index in range(tabs.count())] == [
        '专注陪伴',
        '屏幕舒适',
    ]


def test_break_page_is_focused_without_legacy_application_props():
    controller = _Controller()
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
    assert '更多操作' in top_level
    assert '屏幕舒适与专注' not in top_level


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
