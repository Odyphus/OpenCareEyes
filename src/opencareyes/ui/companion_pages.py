"""Pet-first control-centre pages for OpenCareEyes v0.5."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSignalBlocker, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QBoxLayout,
    QCheckBox,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSlider,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from opencareyes.application.status_presenter import StatusPresenter
from opencareyes.ui.automation_page import AutomationPage, _basename_app_id
from opencareyes.ui.blue_light_page import BlueLightPage
from opencareyes.ui.break_page import BreakPage
from opencareyes.ui.focus_page import FocusPage
from opencareyes.ui.widgets import Card, PageHeader, ScrollPage, first_state_value


class FerretPreview(QWidget):
    """Pet-pack preview stage with a species-neutral painted fallback."""

    def __init__(self, parent=None, *, asset_repository=None):
        super().__init__(parent)
        self._asset_repository = asset_repository
        self.setMinimumSize(240, 220)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setAccessibleName('桌面伙伴预览')
        self._preview_path = ''
        self._preview_pet_id = ''
        self._preview_image = QImage()
        if asset_repository is not None:
            resource_ready = getattr(asset_repository, 'resource_ready', None)
            resource_failed = getattr(asset_repository, 'resource_failed', None)
            if resource_ready is not None:
                resource_ready.connect(self._on_preview_ready)
            if resource_failed is not None:
                resource_failed.connect(self._on_preview_failed)

    def set_preview(
        self,
        path: str,
        display_name: str,
        *,
        pet_id: str = '',
    ) -> None:
        path = str(path or '')
        pet_id = str(pet_id or '')
        if (pet_id, path) != (self._preview_pet_id, self._preview_path):
            self._preview_pet_id = pet_id
            self._preview_path = path
            self._preview_image = QImage()
            self._load_preview()
            self.update()
        self.setAccessibleName(f'{display_name or "桌面伙伴"}预览')

    def _load_preview(self) -> None:
        if (
            self._asset_repository is None
            or not self._preview_pet_id
            or not self._preview_path
        ):
            return
        image = self._asset_repository.load_frame(
            self._preview_pet_id,
            self._preview_path,
        )
        if isinstance(image, QImage) and not image.isNull():
            self._preview_image = QImage(image)

    def _on_preview_ready(self, pet_id: str, resource_path: str) -> None:
        if (str(pet_id), str(resource_path)) != (
            self._preview_pet_id,
            self._preview_path,
        ):
            return
        self._load_preview()
        self.update()

    def _on_preview_failed(self, pet_id: str, resource_path: str) -> None:
        if (str(pet_id), str(resource_path)) != (
            self._preview_pet_id,
            self._preview_path,
        ):
            return
        self._preview_image = QImage()
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        area = QRectF(self.rect()).adjusted(16, 16, -16, -16)
        if not self._preview_image.isNull():
            size = self._preview_image.size()
            scale = min(area.width() / size.width(), area.height() / size.height())
            width = size.width() * scale
            height = size.height() * scale
            target = QRectF(
                area.center().x() - width / 2,
                area.center().y() - height / 2,
                width,
                height,
            )
            painter.setRenderHint(QPainter.SmoothPixmapTransform)
            painter.drawImage(target, self._preview_image)
            return
        centre = area.center()
        scale = min(area.width() / 190.0, area.height() / 150.0)
        painter.translate(centre)
        painter.scale(scale, scale)
        painter.translate(-95, -75)

        tail = QPainterPath(QPointF(65, 112))
        tail.cubicTo(28, 135, 18, 90, 46, 82)
        painter.setPen(QPen(QColor('#111827'), 15, Qt.SolidLine, Qt.RoundCap))
        painter.drawPath(tail)

        painter.setPen(QPen(QColor('#D8E2EC'), 2))
        painter.setBrush(QColor('#F8FAFC'))
        painter.drawEllipse(QRectF(48, 54, 94, 70))
        painter.drawEllipse(QRectF(93, 20, 62, 62))
        painter.drawEllipse(QRectF(101, 13, 18, 24))
        painter.drawEllipse(QRectF(132, 13, 18, 24))

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor('#111827'))
        painter.drawEllipse(QRectF(112, 43, 7, 8))
        painter.drawEllipse(QRectF(137, 43, 7, 8))
        painter.drawEllipse(QRectF(151, 54, 8, 6))
        painter.setBrush(QColor('#F2A6B3'))
        painter.drawEllipse(QRectF(105, 56, 11, 6))
        painter.drawEllipse(QRectF(137, 56, 11, 6))


class CompanionHomePage(ScrollPage):
    """The companion is the primary product surface, not a break add-on."""

    def __init__(self, controller, parent=None, *, asset_repository=None):
        super().__init__(parent)
        self._controller = controller
        self.layout.addWidget(
            PageHeader(
                '陪伴屋',
                '桌面伙伴会陪你学习、提醒休息，也能随时打开常用小工具。',
            )
        )

        self._compact = None
        hero = Card()
        hero.setObjectName('companionHeroCard')
        self._hero_layout = QBoxLayout(QBoxLayout.LeftToRight)
        self._hero_layout.setSpacing(24)
        self._preview = FerretPreview(asset_repository=asset_repository)
        self._preview.setObjectName('companionStage')
        self._hero_layout.addWidget(self._preview, 58)
        copy = QVBoxLayout()
        copy.setSpacing(10)
        eyebrow = QLabel('你的桌面伙伴')
        eyebrow.setObjectName('cardDescription')
        copy.addWidget(eyebrow)
        self._name = QLabel('伙伴')
        self._name.setObjectName('pageTitle')
        self._status = QLabel('正在安静陪伴')
        self._status.setObjectName('statusValue')
        self._detail = QLabel('天气关闭 · 不联网 · 所有数据仅保存在本机')
        self._detail.setWordWrap(True)
        copy.addWidget(self._name)
        copy.addWidget(self._status)
        copy.addWidget(self._detail)
        copy.addStretch()
        actions = QHBoxLayout()
        play = QPushButton('和它玩一下')
        play.setObjectName('secondaryButton')
        play.clicked.connect(lambda: controller.offer_pet_item('yarn_ball'))
        rest = QPushButton('现在休息')
        rest.setObjectName('primaryButton')
        rest.clicked.connect(self._start_rest)
        actions.addWidget(play)
        actions.addWidget(rest)
        copy.addLayout(actions)
        self._hero_layout.addLayout(copy, 42)
        hero.body.addLayout(self._hero_layout)
        self.layout.addWidget(hero)

        self._quick_card = Card('随手工具', '按需运行，不记录使用历史。')
        self._quick_grid = QGridLayout()
        self._quick_grid.setSpacing(8)
        self._quick_buttons = []
        for index, (label, tool_id) in enumerate(
            (
                ('倒计时', 'timer'),
                ('便签', 'notes'),
                ('电脑状态', 'system'),
                ('衣帽间', 'wardrobe'),
            )
        ):
            button = QPushButton(label)
            button.setObjectName('quickToolButton')
            button.setMinimumHeight(42)
            button.clicked.connect(
                lambda _checked=False, selected=tool_id: controller.show_quick_tool(selected)
            )
            self._quick_buttons.append(button)
            self._quick_grid.addWidget(button, index // 2, index % 2)
        self._quick_card.body.addLayout(self._quick_grid)

        self._effects_card = Card('当前实际效果', '状态以真实运行结果为准。')
        self._effects = QLabel()
        self._effects.setObjectName('statusDetail')
        self._effects.setWordWrap(True)
        self._effects_card.body.addWidget(self._effects)
        self._bottom_layout = QBoxLayout(QBoxLayout.LeftToRight)
        self._bottom_layout.setSpacing(16)
        self._bottom_layout.addWidget(self._quick_card, 3)
        self._bottom_layout.addWidget(self._effects_card, 2)
        self.layout.addLayout(self._bottom_layout)
        self.layout.addStretch()

        controller.state_changed.connect(self.render)
        self.render(controller.state)
        self._apply_compact_layout(self.viewport().width() < 640)

    def _start_rest(self) -> None:
        starter = getattr(self._controller, 'start_break_now', None)
        if callable(starter):
            starter()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_compact_layout(self.viewport().width() < 640)

    def _apply_compact_layout(self, compact: bool) -> None:
        if self._compact is compact:
            return
        self._compact = compact
        self._hero_layout.setDirection(
            QBoxLayout.TopToBottom if compact else QBoxLayout.LeftToRight
        )
        self._bottom_layout.setDirection(
            QBoxLayout.TopToBottom if compact else QBoxLayout.LeftToRight
        )
        self.content.layout().setContentsMargins(
            16 if compact else 28,
            16 if compact else 24,
            16 if compact else 28,
            20 if compact else 28,
        )
        if compact:
            self._preview.setMinimumSize(180, 160)
        else:
            self._preview.setMinimumSize(240, 220)
        while self._quick_grid.count():
            self._quick_grid.takeAt(0)
        columns = 2 if compact else 4
        for index, button in enumerate(self._quick_buttons):
            self._quick_grid.addWidget(button, index // columns, index % columns)

    def render(self, state) -> None:
        pet_name = str(
            first_state_value(
                state,
                'pet_catalog.active_display_name',
                default='伙伴',
            )
        )
        if self._name.text() != pet_name:
            self._name.setText(pet_name)
        active_pet_id = str(
            first_state_value(state, 'pet_catalog.active_pet_id', default='')
        )
        catalog = tuple(
            first_state_value(state, 'pet_catalog.available_pets', default=()) or ()
        )
        preview_path = next(
            (
                str(getattr(entry, 'preview_path', ''))
                for entry in catalog
                if str(getattr(entry, 'pet_id', '')) == active_pet_id
            ),
            '',
        )
        self._preview.set_preview(
            preview_path,
            pet_name,
            pet_id=active_pet_id,
        )
        presentation = StatusPresenter.project(state)
        status_text = presentation.headline
        if self._status.text() != status_text:
            self._status.setText(status_text)

        weather_status = str(
            first_state_value(state, 'weather.status', default='disabled')
        )
        weather_text = {
            'disabled': '天气关闭',
            'loading': '天气更新中',
            'ready': '天气装扮已更新',
            'stale': '正在使用稍早天气',
            'failed': '天气暂不可用',
        }.get(weather_status, '天气待更新')
        detail_text = (
            f'{presentation.detail}\n{weather_text} · 不保存互动和应用使用历史'
        )
        if self._detail.text() != detail_text:
            self._detail.setText(detail_text)

        effects_text = '\n'.join(
            f'{effect.label} · {effect.status_text}'
            + (f' · {effect.resume_condition}' if effect.resume_condition else '')
            for effect in presentation.effects
        )
        if self._effects.text() != effects_text:
            self._effects.setText(effects_text)


class PetCatalogPage(ScrollPage):
    """Pet selection, appearance automation, and motion preferences."""

    def __init__(self, controller, parent=None, *, asset_repository=None):
        super().__init__(parent)
        self._controller = controller
        self._asset_repository = asset_repository
        self._rendering = False
        self._catalog_signature = None
        self._compact = None
        self.layout.addWidget(
            PageHeader(
                '宠物图鉴',
                '白鼬是第一位伙伴；后续宠物共用功能，但拥有自己的动作与性格。',
            )
        )

        selector = Card('伙伴选择', '切换伙伴不会中断休息、专注或工具计时。')
        row = QBoxLayout(QBoxLayout.LeftToRight)
        self._selector_layout = row
        self._pet_combo = QComboBox()
        self._pet_combo.setAccessibleName('选择桌面宠物')
        row.addWidget(self._pet_combo, 1)
        self._enabled = QCheckBox('在桌面显示伙伴')
        row.addWidget(self._enabled)
        selector.body.addLayout(row)
        self._personality = QLabel('动作与性格由当前官方宠物包定义。')
        self._personality.setWordWrap(True)
        selector.body.addWidget(self._personality)
        self.layout.addWidget(selector)

        appearance = Card('表现与行为')
        scale_row = QBoxLayout(QBoxLayout.LeftToRight)
        self._scale_layout = scale_row
        scale_row.addWidget(QLabel('大小'))
        self._scale = QSlider(Qt.Horizontal)
        self._scale.setRange(60, 200)
        self._scale.setSingleStep(5)
        self._scale_value = QLabel('100%')
        scale_row.addWidget(self._scale, 1)
        scale_row.addWidget(self._scale_value)
        appearance.body.addLayout(scale_row)
        self._follow = QCheckBox('跟随当前活动显示器')
        self._avoid = QCheckBox('窗口靠近时自动让路')
        self._sound = QCheckBox('允许伙伴音效')
        self._chime = QCheckBox('允许整点报时')
        appearance.body.addWidget(self._follow)
        appearance.body.addWidget(self._avoid)
        appearance.body.addWidget(self._sound)
        appearance.body.addWidget(self._chime)
        countdown_row = QBoxLayout(QBoxLayout.LeftToRight)
        self._countdown_layout = countdown_row
        countdown_row.addWidget(QLabel('休息倒计时'))
        self._countdown_display = QComboBox()
        self._countdown_display.addItem('显示在伙伴气泡', 'floating')
        self._countdown_display.addItem('仅在托盘显示', 'tray')
        self._countdown_display.addItem('完全隐藏', 'hidden')
        self._countdown_display.setAccessibleName('休息倒计时显示位置')
        countdown_row.addWidget(self._countdown_display, 1)
        appearance.body.addLayout(countdown_row)
        self.layout.addWidget(appearance)

        wardrobe = Card(
            '衣帽间',
            '手动锁定装扮会优先于节日和天气；可随时恢复自动搭配。',
        )
        wardrobe_row = QBoxLayout(QBoxLayout.LeftToRight)
        self._wardrobe_layout = wardrobe_row
        self._accessory_buttons: dict[tuple[str, str], QPushButton] = {}
        self._accessory_labels: dict[tuple[str, str], str] = {}
        for label, slot, item_id in (
            ('墨镜', 'headwear', 'sunglasses'),
            ('蓝围巾', 'neckwear', 'scarf'),
            ('红围巾', 'neckwear', 'red_scarf'),
        ):
            button = QPushButton(label)
            button.setCheckable(True)
            button.setAccessibleName(f'装扮：{label}')
            button.clicked.connect(
                lambda checked=False, selected_slot=slot, selected_item=item_id: (
                    self._set_accessory(selected_slot, selected_item, checked)
                )
            )
            key = (slot, item_id)
            self._accessory_buttons[key] = button
            self._accessory_labels[key] = label
            wardrobe_row.addWidget(button)
        clear_wardrobe = QPushButton('恢复自动搭配')
        clear_wardrobe.clicked.connect(self._clear_manual_accessories)
        wardrobe_row.addWidget(clear_wardrobe)
        wardrobe.body.addLayout(wardrobe_row)
        self.layout.addWidget(wardrobe)

        environment = Card(
            '天气与节日',
            '天气默认关闭；开启后会把已配置的经纬度和网络 IP 发送给 Open-Meteo。',
        )
        self._weather = QCheckBox('根据天气自动换装')
        environment.body.addWidget(self._weather)
        source = QLabel('天气数据来源：Open-Meteo · 不记录请求地址和历史天气')
        source.setWordWrap(True)
        environment.body.addWidget(source)
        self.layout.addWidget(environment)

        self.layout.addStretch()
        self._pet_combo.currentIndexChanged.connect(self._select_pet)
        self._enabled.toggled.connect(self._toggle_enabled)
        self._scale.valueChanged.connect(self._preview_scale)
        self._scale.sliderReleased.connect(
            lambda: controller.set_pet_scale(self._scale.value())
        )
        self._follow.toggled.connect(
            lambda value: self._call_unless_rendering(
                controller.set_follow_active_monitor, value
            )
        )
        self._avoid.toggled.connect(
            lambda value: self._call_unless_rendering(
                controller.set_window_avoidance_enabled, value
            )
        )
        self._sound.toggled.connect(
            lambda value: self._call_unless_rendering(
                controller.set_companion_sound_enabled, value
            )
        )
        self._chime.toggled.connect(
            lambda value: self._call_unless_rendering(
                controller.set_hourly_chime_enabled, value
            )
        )
        self._countdown_display.currentIndexChanged.connect(
            self._countdown_display_changed
        )
        self._weather.toggled.connect(self._toggle_weather)
        controller.state_changed.connect(self.render)
        loader = getattr(controller, 'ensure_pet_catalog_loaded', None)
        if (
            callable(loader)
            and hasattr(type(controller), 'ensure_pet_catalog_loaded')
        ):
            loader()
        self.render(controller.state)
        self._apply_compact_layout(self.viewport().width() < 640)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_compact_layout(self.viewport().width() < 640)

    def _apply_compact_layout(self, compact: bool) -> None:
        if self._compact is compact:
            return
        self._compact = compact
        direction = QBoxLayout.TopToBottom if compact else QBoxLayout.LeftToRight
        for layout in (
            self._selector_layout,
            self._scale_layout,
            self._countdown_layout,
            self._wardrobe_layout,
        ):
            layout.setDirection(direction)
        self.content.layout().setContentsMargins(
            16 if compact else 28,
            16 if compact else 24,
            16 if compact else 28,
            20 if compact else 28,
        )

    def _call_unless_rendering(self, command, value) -> None:
        if not self._rendering:
            command(value)

    def _select_pet(self, index: int) -> None:
        if self._rendering or index < 0:
            return
        self._controller.set_active_pet(str(self._pet_combo.itemData(index)))

    def _toggle_enabled(self, enabled: bool) -> None:
        if not self._rendering:
            self._controller.set_companion_enabled(enabled)

    def _preview_scale(self, value: int) -> None:
        self._scale_value.setText(f'{value}%')

    def _toggle_weather(self, enabled: bool) -> None:
        if self._rendering:
            return
        consent = False
        if enabled:
            answer = QMessageBox.question(
                self,
                '开启天气装扮',
                '天气查询会向 Open-Meteo 发送你设置的经纬度和网络 IP，是否继续？',
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            consent = answer == QMessageBox.Yes
            if not consent:
                self._rendering = True
                self._weather.setChecked(False)
                self._rendering = False
                return
        if not self._controller.set_weather_enabled(enabled, consent=consent):
            self.render(self._controller.state)

    def _countdown_display_changed(self, _index: int) -> None:
        if self._rendering:
            return
        setter = getattr(self._controller, 'set_break_countdown_display', None)
        if callable(setter):
            setter(str(self._countdown_display.currentData()))

    def _set_accessory(self, slot: str, item_id: str, checked: bool) -> None:
        if self._rendering:
            return
        if checked:
            for (other_slot, _), button in self._accessory_buttons.items():
                if other_slot == slot and button is not self.sender():
                    with QSignalBlocker(button):
                        button.setChecked(False)
        self._controller.set_pet_accessory(slot, item_id if checked else None)

    def _clear_manual_accessories(self) -> None:
        for slot in ('headwear', 'neckwear', 'bodywear', 'held_item', 'scene', 'effect'):
            self._controller.set_pet_accessory(slot, None)

    def render(self, state) -> None:
        self._rendering = True
        entries = tuple(
            first_state_value(state, 'pet_catalog.available_pets', default=()) or ()
        )
        active = str(
            first_state_value(state, 'pet_catalog.active_pet_id', default='snow_ferret')
        )
        signature = tuple(
            (
                str(getattr(entry, 'pet_id', 'snow_ferret')),
                str(getattr(entry, 'display_name', getattr(entry, 'pet_id', '伙伴'))),
            )
            for entry in entries
        ) or (('snow_ferret', '鼬鼬 · 白鼬'),)
        if signature != self._catalog_signature:
            self._catalog_signature = signature
            with QSignalBlocker(self._pet_combo):
                self._pet_combo.clear()
                for pet_id, display_name in signature:
                    self._pet_combo.addItem(display_name, pet_id)
        index = self._pet_combo.findData(active)
        with QSignalBlocker(self._pet_combo):
            self._pet_combo.setCurrentIndex(max(0, index))
        active_name = (
            self._pet_combo.currentText().strip()
            if self._pet_combo.currentIndex() >= 0
            else '伙伴'
        )
        self._personality.setText(f'{active_name}的动作与性格由官方宠物包定义。')
        with QSignalBlocker(self._enabled):
            self._enabled.setChecked(
                bool(first_state_value(state, 'companion.enabled', default=True))
            )
        scale = int(first_state_value(state, 'companion.scale_percent', default=100))
        with QSignalBlocker(self._scale):
            self._scale.setValue(scale)
        self._preview_scale(scale)
        with QSignalBlocker(self._follow):
            self._follow.setChecked(
                bool(first_state_value(state, 'companion.follow_active_monitor', default=True))
            )
        with QSignalBlocker(self._avoid):
            self._avoid.setChecked(
                bool(
                    first_state_value(
                        state, 'companion.window_avoidance_enabled', default=True
                    )
                )
            )
        with QSignalBlocker(self._sound):
            self._sound.setChecked(
                bool(first_state_value(state, 'companion.sound_enabled', default=False))
            )
        with QSignalBlocker(self._chime):
            self._chime.setChecked(
                bool(
                    first_state_value(
                        state, 'quick_tools.hourly_chime_enabled', default=False
                    )
                )
            )
        countdown_display = str(
            first_state_value(state, 'breaks.countdown_display', default='floating')
        )
        countdown_index = self._countdown_display.findData(countdown_display)
        if countdown_index >= 0:
            with QSignalBlocker(self._countdown_display):
                self._countdown_display.setCurrentIndex(countdown_index)
        weather_status = str(first_state_value(state, 'weather.status', default='disabled'))
        with QSignalBlocker(self._weather):
            self._weather.setChecked(weather_status != 'disabled')
        for (slot, item_id), button in self._accessory_buttons.items():
            selected = str(
                first_state_value(state, f'companion.appearance.{slot}', default='')
            ).replace('\\', '/').lower()
            selected = selected.rsplit('/', 1)[-1].removesuffix('.png')
            is_selected = selected == item_id
            with QSignalBlocker(button):
                button.setChecked(is_selected)
            label = self._accessory_labels[(slot, item_id)]
            button.setText(f'✓ {label} · 已佩戴' if is_selected else label)
            button.setAccessibleName(
                f'装扮：{label}，{"已佩戴" if is_selected else "未佩戴"}'
            )
            object_name = 'secondaryButton' if is_selected else ''
            if button.objectName() != object_name:
                button.setObjectName(object_name)
                button.style().unpolish(button)
                button.style().polish(button)
        self._rendering = False


class AppPropRulesCard(Card):
    """Application-specific companion props, colocated with automation rules."""

    def __init__(self, controller, parent=None):
        super().__init__(
            '应用场景道具',
            '仅保存小写 EXE 文件名，不保存窗口标题、完整路径或使用历史。',
            parent,
        )
        self._controller = controller
        self._current_app_id = ''
        self._app_label = QLabel('当前没有可识别的应用')
        self._app_label.setWordWrap(True)
        self.body.addWidget(self._app_label)
        row = QHBoxLayout()
        self._combo = QComboBox()
        self._combo.addItem('铅笔和尺子', 'writing')
        self._combo.addItem('计算器', 'calculator')
        self._combo.addItem('PCB 元件', 'eda')
        self._save = QPushButton('用于当前应用')
        self._save.setObjectName('secondaryButton')
        self._remove = QPushButton('恢复自动识别')
        self._remove.setObjectName('quietButton')
        self._save.clicked.connect(self._save_rule)
        self._remove.clicked.connect(self._remove_rule)
        row.addWidget(self._combo, 1)
        row.addWidget(self._save)
        row.addWidget(self._remove)
        self.body.addLayout(row)

    def _save_rule(self) -> None:
        if self._current_app_id:
            self._controller.upsert_app_prop_rule(
                self._current_app_id,
                str(self._combo.currentData()),
            )

    def _remove_rule(self) -> None:
        if self._current_app_id:
            self._controller.remove_app_prop_rule(self._current_app_id)

    def render(self, state) -> None:
        foreground = first_state_value(
            state, 'context.foreground_app_id', default=''
        )
        recent = first_state_value(state, 'context.recent_app_id', default='')
        self._current_app_id = _basename_app_id(foreground) or _basename_app_id(recent)
        available = bool(self._current_app_id.endswith('.exe'))
        text = (
            f'当前应用：{self._current_app_id}'
            if available
            else '当前没有可识别的应用'
        )
        if self._app_label.text() != text:
            self._app_label.setText(text)
        self._save.setEnabled(available)
        self._remove.setEnabled(available)


class CompanionAutomationPage(AutomationPage):
    """Automation with companion application-prop rules in one ownership area."""

    def __init__(self, controller, parent=None):
        super().__init__(controller, parent)
        self._app_props = AppPropRulesCard(controller)
        self.layout.insertWidget(max(0, self.layout.count() - 1), self._app_props)
        controller.state_changed.connect(self._app_props.render)
        self._app_props.render(controller.state)


class CompanionBreakPage(BreakPage):
    """Break page limited to cadence, prompting and scene choices."""

    def __init__(self, controller, parent=None):
        super().__init__(controller, parent)
        self._reminder_card.body.addWidget(self._force_toggle)
        self._pet_card.hide()
        self._advanced_card.hide()


class StudyDeskPage(QWidget):
    """Keep mature display/focus controls while presenting them as pet abilities."""

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        tabs = QTabWidget()
        tabs.setAccessibleName('学习桌工具分类')
        tabs.addTab(FocusPage(controller), '专注陪伴')
        tabs.addTab(BlueLightPage(controller), '屏幕舒适')
        layout.addWidget(tabs)
