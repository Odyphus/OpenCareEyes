"""Pet-first control-centre pages for OpenCareEyes v0.5."""

from __future__ import annotations

from PySide6.QtCore import (
    QAbstractListModel,
    QModelIndex,
    QPointF,
    QRectF,
    QSignalBlocker,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QAccessible,
    QAccessibleEvent,
    QColor,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QBoxLayout,
    QCheckBox,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListView,
    QPushButton,
    QSlider,
    QSizePolicy,
    QStyle,
    QStyledItemDelegate,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from opencareyes.application.status_presenter import StatusPresenter
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


class _WardrobeModel(QAbstractListModel):
    """Small manifest projection with on-paint thumbnail loading."""

    EntryRole = Qt.UserRole + 1
    EffectiveRole = Qt.UserRole + 2
    AvailableRole = Qt.UserRole + 3
    LoadingRole = Qt.UserRole + 4

    def __init__(self, parent=None, *, asset_repository=None):
        super().__init__(parent)
        self._asset_repository = asset_repository
        self._pet_id = ''
        self._entries: tuple[object, ...] = ()
        self._effective_id = ''
        self._loading_id = ''
        self._images: dict[str, QImage] = {}
        self._requested: set[str] = set()
        self._failed: set[str] = set()
        if asset_repository is not None:
            resource_ready = getattr(asset_repository, 'resource_ready', None)
            resource_failed = getattr(asset_repository, 'resource_failed', None)
            if resource_ready is not None:
                resource_ready.connect(self._on_resource_ready)
            if resource_failed is not None:
                resource_failed.connect(self._on_resource_failed)

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._entries)

    def data(self, index, role=Qt.DisplayRole):
        entry = self.entry(index)
        if entry is None:
            return None
        outfit_id = str(getattr(entry, 'outfit_id', ''))
        display_name = str(getattr(entry, 'display_name', outfit_id or '未命名造型'))
        description = str(getattr(entry, 'description', ''))
        available = self.is_available(index)
        effective = bool(outfit_id and outfit_id == self._effective_id)
        loading = bool(outfit_id and outfit_id == self._loading_id)
        if role == Qt.DisplayRole:
            return display_name
        if role == Qt.ToolTipRole:
            return description
        if role == Qt.AccessibleTextRole:
            status = '正在穿戴' if loading else ('已穿戴' if effective else '未穿戴')
            return f'装扮：{display_name}，{status}'
        if role == Qt.AccessibleDescriptionRole:
            suffix = '资源可用' if available else '资源不可用'
            return f'{description}；{suffix}' if description else suffix
        if role == self.EntryRole:
            return entry
        if role == self.EffectiveRole:
            return effective
        if role == self.AvailableRole:
            return available
        if role == self.LoadingRole:
            return loading
        return None

    def set_context(
        self,
        pet_id: str,
        entries: tuple[object, ...],
        *,
        effective_id: str,
        loading_id: str,
    ) -> None:
        entries = tuple(entries)
        signature = tuple(
            (
                str(getattr(entry, 'outfit_id', '')),
                str(getattr(entry, 'display_name', '')),
                str(getattr(entry, 'description', '')),
                str(getattr(entry, 'thumbnail_path', '')),
                bool(getattr(entry, 'available', True)),
            )
            for entry in entries
        )
        current_signature = tuple(
            (
                str(getattr(entry, 'outfit_id', '')),
                str(getattr(entry, 'display_name', '')),
                str(getattr(entry, 'description', '')),
                str(getattr(entry, 'thumbnail_path', '')),
                bool(getattr(entry, 'available', True)),
            )
            for entry in self._entries
        )
        pet_changed = str(pet_id) != self._pet_id
        if pet_changed or signature != current_signature:
            self.beginResetModel()
            self._pet_id = str(pet_id)
            self._entries = entries
            self._images.clear()
            self._requested.clear()
            self._failed.clear()
            self._effective_id = str(effective_id)
            self._loading_id = str(loading_id)
            self.endResetModel()
            return
        changed = (
            self._effective_id != str(effective_id)
            or self._loading_id != str(loading_id)
        )
        self._effective_id = str(effective_id)
        self._loading_id = str(loading_id)
        if changed and self._entries:
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(len(self._entries) - 1, 0),
                [self.EffectiveRole, self.LoadingRole, Qt.AccessibleTextRole],
            )

    def entry(self, index) -> object | None:
        row = index.row() if isinstance(index, QModelIndex) else int(index)
        return self._entries[row] if 0 <= row < len(self._entries) else None

    def index_for_outfit(self, outfit_id: str) -> QModelIndex:
        for row, entry in enumerate(self._entries):
            if str(getattr(entry, 'outfit_id', '')) == str(outfit_id):
                return self.index(row, 0)
        return QModelIndex()

    def is_available(self, index) -> bool:
        entry = self.entry(index)
        if entry is None:
            return False
        path = str(getattr(entry, 'thumbnail_path', ''))
        return bool(getattr(entry, 'available', True)) and path not in self._failed

    def thumbnail(self, index) -> QImage:
        entry = self.entry(index)
        if entry is None:
            return QImage()
        return QImage(self._images.get(str(getattr(entry, 'thumbnail_path', '')), QImage()))

    def thumbnail_placeholder(self, index) -> str:
        entry = self.entry(index)
        if entry is None:
            return '资源不可用'
        path = str(getattr(entry, 'thumbnail_path', ''))
        if (
            self._asset_repository is None
            or not bool(getattr(entry, 'available', True))
            or path in self._failed
        ):
            return '资源不可用'
        return '预览加载中'

    def ensure_thumbnail(self, index) -> None:
        entry = self.entry(index)
        if entry is None or self._asset_repository is None:
            return
        path = str(getattr(entry, 'thumbnail_path', ''))
        if not path or not bool(getattr(entry, 'available', True)):
            return
        if path in self._images or path in self._requested or path in self._failed:
            return
        self._requested.add(path)
        image = self._asset_repository.load_frame(self._pet_id, path)
        if isinstance(image, QImage) and not image.isNull():
            self._images[path] = QImage(image)
            self._emit_path_changed(path)

    def _on_resource_ready(self, pet_id: str, resource_path: str) -> None:
        path = str(resource_path)
        if str(pet_id) != self._pet_id or path not in self._requested:
            return
        image = self._asset_repository.load_frame(self._pet_id, path)
        if isinstance(image, QImage) and not image.isNull():
            self._images[path] = QImage(image)
            self._failed.discard(path)
            self._emit_path_changed(path)

    def _on_resource_failed(self, pet_id: str, resource_path: str) -> None:
        path = str(resource_path)
        if str(pet_id) != self._pet_id or path not in self._requested:
            return
        self._failed.add(path)
        self._emit_path_changed(path)

    def _emit_path_changed(self, path: str) -> None:
        for row, entry in enumerate(self._entries):
            if str(getattr(entry, 'thumbnail_path', '')) == path:
                index = self.index(row, 0)
                self.dataChanged.emit(
                    index,
                    index,
                    [self.AvailableRole, Qt.AccessibleDescriptionRole],
                )


class _WardrobeDelegate(QStyledItemDelegate):
    """Paint an accessible card without relying on colour alone."""

    def paint(self, painter, option, index) -> None:
        model = index.model()
        model.ensure_thumbnail(index)
        entry = index.data(_WardrobeModel.EntryRole)
        if entry is None:
            return
        display_name = str(getattr(entry, 'display_name', '未命名造型'))
        effective = bool(index.data(_WardrobeModel.EffectiveRole))
        available = bool(index.data(_WardrobeModel.AvailableRole))
        loading = bool(index.data(_WardrobeModel.LoadingRole))
        current = bool(option.state & QStyle.State_Selected)
        focused = bool(option.state & QStyle.State_HasFocus)
        hovered = bool(option.state & QStyle.State_MouseOver)
        pressed = bool(option.state & QStyle.State_Sunken)

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        card = QRectF(option.rect).adjusted(4, 4, -4, -4)
        palette = option.palette
        background = palette.window().color()
        if effective:
            background = QColor(palette.highlight().color())
            background.setAlpha(34)
        elif current or hovered:
            background = QColor(palette.highlight().color())
            background.setAlpha(20 if current else 12)
        if pressed:
            background = background.darker(106)
        border = (
            palette.highlight().color()
            if effective or current
            else palette.mid().color()
        )
        painter.setBrush(background)
        painter.setPen(QPen(border, 3 if effective else (2 if current else 1)))
        painter.drawRoundedRect(card, 12, 12)

        image_size = max(112.0, min(184.0, card.width() - 20.0))
        image_rect = QRectF(
            card.center().x() - image_size / 2,
            card.top() + 10,
            image_size,
            image_size,
        )
        image = model.thumbnail(index)
        if not image.isNull():
            painter.setRenderHint(QPainter.SmoothPixmapTransform)
            source = QRectF(image.rect())
            source_ratio = source.width() / max(1.0, source.height())
            target = QRectF(image_rect)
            if source_ratio > 1:
                target.setHeight(target.width() / source_ratio)
            else:
                target.setWidth(target.height() * source_ratio)
            target.moveCenter(image_rect.center())
            painter.drawImage(target, image, source)
        else:
            painter.setPen(QPen(palette.mid().color(), 1))
            painter.setBrush(palette.window().color())
            painter.drawRoundedRect(image_rect, 8, 8)
            painter.setPen(palette.placeholderText().color())
            painter.drawText(
                image_rect,
                Qt.AlignCenter,
                model.thumbnail_placeholder(index),
            )

        font = painter.font()
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(palette.text().color() if available else palette.placeholderText().color())
        name_rect = QRectF(
            card.left() + 10,
            image_rect.bottom() + 8,
            card.width() - 20,
            24,
        )
        painter.drawText(name_rect, Qt.AlignCenter, display_name)

        status_rect = QRectF(card.left() + 10, name_rect.bottom() + 2, card.width() - 20, 20)
        font.setBold(False)
        painter.setFont(font)
        if loading:
            painter.setPen(palette.highlight().color())
            painter.drawText(status_rect, Qt.AlignCenter, '正在穿戴…')
        elif effective:
            painter.setPen(palette.highlight().color())
            painter.drawText(status_rect, Qt.AlignCenter, '✓  已穿戴')
        elif current and available:
            painter.setPen(palette.highlight().color())
            painter.drawText(status_rect, Qt.AlignCenter, '双击立即穿戴')
        elif not available:
            painter.setPen(palette.placeholderText().color())
            painter.drawText(status_rect, Qt.AlignCenter, '资源不可用')

        if focused:
            focus = card.adjusted(3, 3, -3, -3)
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(palette.highlight().color(), 2, Qt.DashLine))
            painter.drawRoundedRect(focus, 9, 9)
        painter.restore()

    def sizeHint(self, _option, _index) -> QSize:
        return QSize(188, 264)


class _WardrobeListView(QListView):
    wear_requested = Signal()

    def mouseDoubleClickEvent(self, event) -> None:
        index = self.indexAt(event.position().toPoint())
        if index.isValid():
            self.setCurrentIndex(index)
            self.wear_requested.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.wear_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)


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
        self._detail = QLabel('本地运行 · 所有数据仅保存在本机')
        self._detail.setWordWrap(True)
        copy.addWidget(self._name)
        copy.addWidget(self._status)
        copy.addWidget(self._detail)
        copy.addStretch()
        actions = QHBoxLayout()
        rest = QPushButton('现在休息')
        rest.setObjectName('primaryButton')
        rest.clicked.connect(self._start_rest)
        actions.addStretch()
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

        detail_text = (
            f'{presentation.detail}\n本地运行 · 不保存互动或应用使用历史'
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
        self._active_pet_id = ''
        self._last_wardrobe_state = None
        self._last_wardrobe_announcement = ''
        self._loading_outfit_id = ''
        self.layout.addWidget(
            PageHeader(
                '宠物图鉴',
                '白鼬是第一位伙伴；后续宠物共用功能，但拥有自己的动作与性格。',
            )
        )

        self._wardrobe_card = self._build_wardrobe_card()
        self.layout.addWidget(self._wardrobe_card)

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
        self._scale.setAccessibleName('桌面伙伴大小')
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
        controller.state_changed.connect(self.render)
        wardrobe_changed = getattr(controller, 'wardrobe_changed', None)
        if wardrobe_changed is not None and hasattr(wardrobe_changed, 'connect'):
            wardrobe_changed.connect(self.render_wardrobe)
        loader = getattr(controller, 'ensure_pet_catalog_loaded', None)
        if (
            callable(loader)
            and hasattr(type(controller), 'ensure_pet_catalog_loaded')
        ):
            loader()
        self.render(controller.state)
        self._apply_compact_layout(self.viewport().width() < 640)
        self._apply_wardrobe_grid(self.viewport().width())

    def _build_wardrobe_card(self) -> Card:
        wardrobe = Card(
            '百变衣橱',
            '单击查看大图，双击立即穿戴；也可按 Enter 或 Space 应用当前造型。',
        )
        self._wardrobe_status = QLabel('当前：默认外观')
        self._wardrobe_status.setObjectName('statusValue')
        self._wardrobe_status.setAccessibleName('当前造型状态')
        wardrobe.body.addWidget(self._wardrobe_status)

        self._wardrobe_content = QWidget()
        content_layout = QBoxLayout(QBoxLayout.RightToLeft)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(12)
        self._wardrobe_content.setLayout(content_layout)
        self._wardrobe_content_layout = content_layout

        self._wardrobe_detail_panel = QWidget()
        self._wardrobe_detail_panel.setObjectName('wardrobeDetailPanel')
        self._wardrobe_detail_panel.setMinimumWidth(220)
        self._wardrobe_detail_panel.setMaximumWidth(280)
        detail_layout = QVBoxLayout(self._wardrobe_detail_panel)
        detail_layout.setContentsMargins(16, 16, 16, 16)
        detail_layout.setSpacing(10)
        self._wardrobe_detail_preview = QLabel('选择造型查看大图')
        self._wardrobe_detail_preview.setObjectName('wardrobeDetailPreview')
        self._wardrobe_detail_preview.setAccessibleName('当前浏览造型预览')
        self._wardrobe_detail_preview.setAlignment(Qt.AlignCenter)
        self._wardrobe_detail_preview.setMinimumHeight(180)
        self._wardrobe_detail_preview.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Fixed,
        )
        self._wardrobe_detail_title = QLabel('选择一套造型查看详情')
        self._wardrobe_detail_title.setObjectName('cardHeading')
        self._wardrobe_detail = QLabel('')
        self._wardrobe_detail.setObjectName('statusDetail')
        self._wardrobe_detail.setWordWrap(True)
        self._wardrobe_error = QLabel('')
        self._wardrobe_error.setObjectName('errorLabel')
        self._wardrobe_error.setAccessibleName('衣橱资源错误')
        self._wardrobe_error.setWordWrap(True)
        detail_layout.addWidget(self._wardrobe_detail_preview)
        detail_layout.addWidget(self._wardrobe_detail_title)
        detail_layout.addWidget(self._wardrobe_detail)
        detail_layout.addWidget(self._wardrobe_error)

        action_row = QBoxLayout(QBoxLayout.LeftToRight)
        self._wardrobe_action_layout = action_row
        self._wear_outfit = QPushButton('穿戴这套')
        self._wear_outfit.setObjectName('primaryButton')
        self._wear_outfit.setAccessibleName('穿戴当前浏览的整套造型')
        self._wear_outfit.setMinimumHeight(40)
        self._restore_outfit = QPushButton('恢复默认外观')
        self._restore_outfit.setObjectName('quietButton')
        self._restore_outfit.setAccessibleName('恢复伙伴默认外观')
        self._restore_outfit.setMinimumHeight(40)
        action_row.addWidget(self._wear_outfit)
        action_row.addWidget(self._restore_outfit)
        detail_layout.addLayout(action_row)

        self._wardrobe_mode_note = QLabel(
            '完整造型只改变伙伴外观，不影响休息、专注和互动逻辑。'
        )
        self._wardrobe_mode_note.setObjectName('statusDetail')
        self._wardrobe_mode_note.setWordWrap(True)
        detail_layout.addWidget(self._wardrobe_mode_note)
        detail_layout.addStretch()
        content_layout.addWidget(self._wardrobe_detail_panel)

        self._wardrobe_gallery = QWidget()
        gallery_layout = QVBoxLayout(self._wardrobe_gallery)
        gallery_layout.setContentsMargins(0, 0, 0, 0)
        gallery_layout.setSpacing(8)
        self._wardrobe_model = _WardrobeModel(
            wardrobe,
            asset_repository=self._asset_repository,
        )
        self._wardrobe_view = _WardrobeListView()
        self._wardrobe_view.setObjectName('wardrobeGallery')
        self._wardrobe_view.setAccessibleName('整套造型图鉴')
        self._wardrobe_view.setAccessibleDescription(
            '单击查看大图，双击穿戴；也可用方向键浏览并按 Enter 或 Space 穿戴。'
        )
        self._wardrobe_view.setModel(self._wardrobe_model)
        self._wardrobe_view.setItemDelegate(_WardrobeDelegate(self._wardrobe_view))
        self._wardrobe_view.setViewMode(QListView.IconMode)
        self._wardrobe_view.setFlow(QListView.LeftToRight)
        self._wardrobe_view.setWrapping(True)
        self._wardrobe_view.setResizeMode(QListView.Adjust)
        self._wardrobe_view.setMovement(QListView.Static)
        self._wardrobe_view.setUniformItemSizes(True)
        self._wardrobe_view.setMouseTracking(True)
        self._wardrobe_view.setSelectionMode(QAbstractItemView.SingleSelection)
        self._wardrobe_view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._wardrobe_view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._wardrobe_view.setSpacing(8)
        self._wardrobe_empty = QLabel(
            '当前伙伴尚未提供完整造型，将继续使用默认外观。'
        )
        self._wardrobe_empty.setObjectName('statusDetail')
        self._wardrobe_empty.setAccessibleName('衣橱空状态')
        self._wardrobe_empty.setWordWrap(True)
        gallery_layout.addWidget(self._wardrobe_empty)
        gallery_layout.addWidget(self._wardrobe_view)
        content_layout.addWidget(self._wardrobe_gallery, 1)
        wardrobe.body.addWidget(self._wardrobe_content)

        self._wardrobe_view.selectionModel().currentChanged.connect(
            lambda _current, _previous: self._update_wardrobe_detail()
        )
        self._wardrobe_model.dataChanged.connect(
            lambda _top_left, _bottom_right, _roles: (
                self._update_wardrobe_detail()
            )
        )
        self._wardrobe_view.wear_requested.connect(self._wear_selected_outfit)
        self._wear_outfit.clicked.connect(self._wear_selected_outfit)
        self._restore_outfit.clicked.connect(
            lambda: self._controller.set_pet_outfit(None)
        )
        return wardrobe

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_compact_layout(self.viewport().width() < 640)
        self._apply_wardrobe_grid(self.viewport().width())

    def _apply_compact_layout(self, compact: bool) -> None:
        if self._compact is compact:
            return
        self._compact = compact
        direction = QBoxLayout.TopToBottom if compact else QBoxLayout.LeftToRight
        for layout in (
            self._selector_layout,
            self._scale_layout,
            self._countdown_layout,
            self._wardrobe_action_layout,
        ):
            layout.setDirection(direction)
        self._wardrobe_content_layout.setDirection(
            QBoxLayout.TopToBottom if compact else QBoxLayout.RightToLeft
        )
        self._wardrobe_detail_panel.setMinimumWidth(0 if compact else 220)
        self._wardrobe_detail_panel.setMaximumWidth(16_777_215 if compact else 280)
        self.content.layout().setContentsMargins(
            16 if compact else 28,
            16 if compact else 24,
            16 if compact else 28,
            20 if compact else 28,
        )

    def _apply_wardrobe_grid(self, available_width: int) -> None:
        has_items = self._wardrobe_model.rowCount() > 0
        self._wardrobe_empty.setVisible(not has_items)
        self._wardrobe_view.setVisible(has_items)
        if not has_items:
            self._wardrobe_columns = 0
            self._wardrobe_view.setFixedHeight(0)
            return

        gallery_width = self._wardrobe_gallery.width()
        if gallery_width < 240:
            reserved = 0 if self._compact else 300
            margins = 32 if self._compact else 56
            gallery_width = max(240, int(available_width) - reserved - margins)
        if self._compact:
            columns = 1 if gallery_width < 380 else 2
        elif gallery_width < 380:
            columns = 1
        elif gallery_width < 620:
            columns = 2
        else:
            columns = 3
        spacing = self._wardrobe_view.spacing()
        cell_width = max(
            176,
            (gallery_width - spacing * (columns - 1)) // columns,
        )
        cell_height = 264
        self._wardrobe_columns = columns
        self._wardrobe_view.setGridSize(QSize(cell_width, cell_height))
        rows = (self._wardrobe_model.rowCount() + columns - 1) // columns
        self._wardrobe_view.setFixedHeight(rows * cell_height + 4)

    def focus_wardrobe(self) -> None:
        '''Reveal the wardrobe and focus the effective or first outfit.'''

        self.ensureWidgetVisible(self._wardrobe_card, 0, 16)
        if not self._wardrobe_view.currentIndex().isValid():
            effective = str(
                first_state_value(
                    self._controller.state,
                    'pet_wardrobe.effective_outfit_id',
                    'pet_wardrobe.selected_outfit_id',
                    default='',
                )
            )
            target = self._wardrobe_model.index_for_outfit(effective)
            if not target.isValid() and self._wardrobe_model.rowCount():
                target = self._wardrobe_model.index(0, 0)
            if target.isValid():
                self._wardrobe_view.setCurrentIndex(target)
        self._wardrobe_view.setFocus(Qt.ShortcutFocusReason)

    def _selected_outfit_entry(self) -> object | None:
        return self._wardrobe_model.entry(self._wardrobe_view.currentIndex())

    def _wear_selected_outfit(self) -> None:
        if self._loading_outfit_id:
            return
        entry = self._selected_outfit_entry()
        if entry is None or not self._wardrobe_model.is_available(
            self._wardrobe_view.currentIndex()
        ):
            return
        outfit_id = str(getattr(entry, 'outfit_id', ''))
        if outfit_id:
            self._controller.set_pet_outfit(outfit_id)

    def _update_wardrobe_detail(self) -> None:
        entry = self._selected_outfit_entry()
        if entry is None:
            empty = self._wardrobe_model.rowCount() == 0
            self._wardrobe_detail_preview.clear()
            self._wardrobe_detail_preview.setText(
                '暂无造型' if empty else '选择造型查看大图'
            )
            self._wardrobe_detail_title.setText(
                '暂无整套造型' if empty else '选择一套造型查看详情'
            )
            self._wardrobe_detail.setText(
                '当前伙伴将继续使用默认外观。' if empty else ''
            )
            self._wear_outfit.setEnabled(False)
            self._wear_outfit.setText('穿戴这套')
            return
        display_name = str(getattr(entry, 'display_name', '未命名造型'))
        description = str(getattr(entry, 'description', '暂无造型说明。'))
        current = self._wardrobe_view.currentIndex()
        available = self._wardrobe_model.is_available(current)
        effective = bool(current.data(_WardrobeModel.EffectiveRole))
        loading = bool(self._loading_outfit_id)
        self._wardrobe_model.ensure_thumbnail(current)
        image = self._wardrobe_model.thumbnail(current)
        self._wardrobe_detail_preview.clear()
        if image.isNull():
            self._wardrobe_detail_preview.setText(
                self._wardrobe_model.thumbnail_placeholder(current)
            )
        else:
            pixmap = QPixmap.fromImage(image).scaled(
                220,
                180,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
            self._wardrobe_detail_preview.setPixmap(pixmap)
        self._wardrobe_detail_title.setText(display_name)
        self._wardrobe_detail.setText(
            description if available else f'{description}\n资源不可用，当前造型不会改变。'
        )
        self._wear_outfit.setEnabled(available and not effective and not loading)
        if loading:
            self._wear_outfit.setText('正在应用…')
        else:
            self._wear_outfit.setText('已穿戴' if effective else '穿戴这套')

    def render_wardrobe(self, wardrobe_state) -> None:
        """Apply a lightweight wardrobe projection without rebuilding the page."""

        previous_rendering = self._rendering
        self._rendering = True
        try:
            self._apply_wardrobe_state(wardrobe_state)
        finally:
            self._rendering = previous_rendering

    def _apply_wardrobe_state(self, wardrobe_state) -> None:
        wardrobe_state = getattr(wardrobe_state, 'pet_wardrobe', wardrobe_state)
        self._last_wardrobe_state = wardrobe_state
        wardrobe_entries = tuple(
            getattr(wardrobe_state, 'available_outfits', ()) or ()
        )
        wardrobe_mode = str(getattr(wardrobe_state, 'mode', 'automatic'))
        selected_outfit = str(
            getattr(wardrobe_state, 'selected_outfit_id', '')
        )
        effective_outfit = str(
            getattr(wardrobe_state, 'effective_outfit_id', '')
        )
        loading_outfit = str(
            getattr(wardrobe_state, 'loading_outfit_id', '')
        )
        self._loading_outfit_id = loading_outfit

        browsed = self._selected_outfit_entry()
        browsed_id = str(getattr(browsed, 'outfit_id', '')) if browsed else ''
        self._wardrobe_model.set_context(
            self._active_pet_id,
            wardrobe_entries,
            effective_id=effective_outfit,
            loading_id=loading_outfit,
        )
        target = self._wardrobe_model.index_for_outfit(browsed_id)
        if not target.isValid():
            target = self._wardrobe_model.index_for_outfit(
                effective_outfit or selected_outfit
            )
        if not target.isValid() and self._wardrobe_model.rowCount():
            target = self._wardrobe_model.index(0, 0)
        if target.isValid() and target != self._wardrobe_view.currentIndex():
            self._wardrobe_view.setCurrentIndex(target)

        names = {
            str(getattr(entry, 'outfit_id', '')): str(
                getattr(entry, 'display_name', '未命名造型')
            )
            for entry in wardrobe_entries
        }
        if loading_outfit:
            wardrobe_status = (
                f'正在穿戴：{names.get(loading_outfit, loading_outfit)}'
            )
        elif wardrobe_mode == 'outfit' and effective_outfit:
            wardrobe_status = (
                f'已锁定：{names.get(effective_outfit, effective_outfit)}'
            )
        else:
            wardrobe_status = '当前：默认外观'
        self._wardrobe_status.setText(wardrobe_status)

        wardrobe_error = str(getattr(wardrobe_state, 'error', ''))
        self._wardrobe_error.setText(wardrobe_error)
        self._wardrobe_error.setVisible(bool(wardrobe_error))
        self._wardrobe_mode_note.setText(
            '双击其他造型即可直接切换；休息和互动逻辑保持不变。'
            if wardrobe_mode == 'outfit' and bool(effective_outfit)
            else '完整造型只改变伙伴外观，不影响休息、专注和互动逻辑。'
        )
        self._restore_outfit.setEnabled(
            wardrobe_mode != 'automatic' and not loading_outfit
        )
        self._update_wardrobe_detail()
        self._apply_wardrobe_grid(self.viewport().width())

        announcement = wardrobe_error or wardrobe_status
        self._wardrobe_status.setAccessibleDescription(announcement)
        if announcement != self._last_wardrobe_announcement:
            self._last_wardrobe_announcement = announcement
            alert_event = getattr(QAccessible.Event, 'Alert', None)
            if alert_event is not None and self.isVisible():
                QAccessible.updateAccessibility(
                    QAccessibleEvent(self._wardrobe_status, alert_event)
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

    def _countdown_display_changed(self, _index: int) -> None:
        if self._rendering:
            return
        setter = getattr(self._controller, 'set_break_countdown_display', None)
        if callable(setter):
            setter(str(self._countdown_display.currentData()))

    def render(self, state) -> None:
        previous_rendering = self._rendering
        self._rendering = True
        try:
            self._render_state(state)
        finally:
            self._rendering = previous_rendering

    def _render_state(self, state) -> None:
        entries = tuple(
            first_state_value(state, 'pet_catalog.available_pets', default=()) or ()
        )
        active = str(
            first_state_value(state, 'pet_catalog.active_pet_id', default='')
        )
        self._active_pet_id = active
        self._apply_wardrobe_state(
            getattr(state, 'pet_wardrobe', state)
        )
        signature = tuple(
            (
                str(getattr(entry, 'pet_id', '')),
                str(getattr(entry, 'display_name', getattr(entry, 'pet_id', '伙伴'))),
            )
            for entry in entries
            if str(getattr(entry, 'pet_id', ''))
        )
        if not signature and active:
            signature = ((active, active.replace('_', ' ').strip() or '伙伴'),)
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
