'''Independent quick-action bubble shown beside the desktop companion.'''

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QRectF, Signal, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPalette, QPen
from PySide6.QtWidgets import (
    QApplication,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


_THEMES = {
    'dark': {
        'card': '#151C29',
        'border': '#35415A',
        'title': '#F7FAFF',
        'text': '#C4CFE1',
        'button': '#222C3E',
        'button_hover': '#2D3A52',
    },
    'light': {
        'card': '#F8FBFF',
        'border': '#CAD5E5',
        'title': '#182236',
        'text': '#58677F',
        'button': '#EAF0FA',
        'button_hover': '#DDE7F6',
    },
}


class PetBubble(QWidget):
    '''Non-modal companion toolbar with no private countdown timer.'''

    tool_requested = Signal(str)
    item_requested = Signal(str)
    dismissed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._theme = 'dark'
        self._high_contrast = False
        self._theme_signature = None
        self._active_palette = dict(_THEMES['dark'])
        self._anchor_rect: QRect | None = None
        self._anchor_target = None

        self.setObjectName('petBubble')
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self.setFixedSize(342, 220)
        self.setAccessibleName('桌面伙伴快捷气泡')

        self._build_ui()
        self.set_theme('dark')

    @property
    def theme(self) -> str:
        return self._theme

    @property
    def tool_buttons(self) -> dict[str, QPushButton]:
        return dict(self._tool_buttons)

    @property
    def item_buttons(self) -> dict[str, QPushButton]:
        return dict(self._item_buttons)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 14, 14)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.setSpacing(8)
        self._title = QLabel('伙伴在陪你')
        self._title.setFont(QFont('Microsoft YaHei UI', 10, QFont.DemiBold))
        self._title.setAccessibleName('伙伴状态')
        header.addWidget(self._title, 1)

        self._close = QToolButton(self)
        self._close.setText('×')
        self._close.setFixedSize(24, 24)
        self._close.setAccessibleName('关闭伙伴快捷气泡')
        self._close.setToolTip('关闭')
        self._close.clicked.connect(self.hide)
        header.addWidget(self._close)
        layout.addLayout(header)

        self._detail = QLabel('距离下次休息')
        self._detail.setFont(QFont('Microsoft YaHei UI', 9))
        self._detail.setWordWrap(True)
        self._detail.setAccessibleName('伙伴状态说明')
        layout.addWidget(self._detail)

        self._countdown = QLabel('--:--')
        self._countdown.setFont(QFont('Microsoft YaHei UI', 20, QFont.DemiBold))
        self._countdown.setAccessibleName('休息倒计时')
        layout.addWidget(self._countdown)

        tools = QGridLayout()
        tools.setHorizontalSpacing(7)
        tools.setVerticalSpacing(7)
        definitions = (
            ('rest', '立即休息'),
            ('timer', '计时器'),
            ('note', '便签'),
            ('status', '状态'),
        )
        self._tool_buttons: dict[str, QPushButton] = {}
        for column, (tool_id, label) in enumerate(definitions):
            button = QPushButton(label)
            button.setCursor(Qt.PointingHandCursor)
            button.setAccessibleName(label)
            button.clicked.connect(
                lambda _checked=False, selected=tool_id: self.tool_requested.emit(selected)
            )
            tools.addWidget(button, 0, column)
            self._tool_buttons[tool_id] = button
        self._item_buttons: dict[str, QPushButton] = {}
        for column, (item_id, label) in enumerate(
            (
                ('yarn_ball', '毛线球'),
                ('hot_cocoa', '热可可'),
                ('pine_cone', '松果'),
            )
        ):
            button = QPushButton(label)
            button.setCursor(Qt.PointingHandCursor)
            button.setAccessibleName(f'给伙伴{label}')
            button.clicked.connect(
                lambda _checked=False, selected=item_id: self.item_requested.emit(
                    selected
                )
            )
            tools.addWidget(button, 1, column)
            self._item_buttons[item_id] = button
        layout.addLayout(tools)

    def set_status(self, title: str, detail: str = '') -> None:
        self._title.setText(str(title))
        self._detail.setText(str(detail))

    def set_break_countdown(self, remaining: int, total: int | None = None) -> None:
        '''Update displayed text only; authoritative timing remains elsewhere.'''

        del total
        seconds = max(0, int(remaining))
        minutes, seconds = divmod(seconds, 60)
        self._countdown.setText(f'{minutes}:{seconds:02d}')

    def set_quick_actions(self, actions) -> None:
        selected = {str(action).strip().lower() for action in actions}
        aliases = {'note': 'notes', 'status': 'system'}
        for tool_id, button in self._tool_buttons.items():
            semantic = aliases.get(tool_id, tool_id)
            button.setVisible(semantic in selected)

    def set_theme(self, theme) -> None:
        resolved = getattr(theme, 'resolved', theme)
        high_contrast = bool(getattr(theme, 'high_contrast', False))
        resolved = resolved if resolved in _THEMES else 'dark'
        signature = (resolved, high_contrast)
        if signature == self._theme_signature:
            return
        self._theme_signature = signature
        self._theme = resolved
        self._high_contrast = high_contrast
        if high_contrast:
            native = self.palette()
            palette = {
                'card': native.color(QPalette.Window).name(),
                'border': native.color(QPalette.Mid).name(),
                'title': native.color(QPalette.WindowText).name(),
                'text': native.color(QPalette.Text).name(),
                'button': native.color(QPalette.AlternateBase).name(),
                'button_hover': native.color(QPalette.Highlight).name(),
            }
        else:
            palette = dict(_THEMES[self._theme])
        self._active_palette = palette
        title_color = palette['title']
        text_color = palette['text']
        button_color = palette['button']
        hover_color = palette['button_hover']
        self._title.setStyleSheet(f'color: {title_color}; background: transparent;')
        self._detail.setStyleSheet(f'color: {text_color}; background: transparent;')
        self._countdown.setStyleSheet(f'color: {title_color}; background: transparent;')
        self._close.setStyleSheet(
            'QToolButton { border: none; border-radius: 12px; background: transparent; '
            f'color: {text_color}; font-size: 17px; }} '
            f'QToolButton:hover {{ background: {button_color}; }}'
        )
        button_style = (
            'QPushButton { border: none; border-radius: 8px; padding: 6px 8px; '
            f'background: {button_color}; color: {title_color}; }} '
            f'QPushButton:hover, QPushButton:focus {{ background: {hover_color}; }}'
        )
        for button in (*self._tool_buttons.values(), *self._item_buttons.values()):
            button.setStyleSheet(button_style)
        self.update()

    def show_for(self, anchor) -> None:
        '''Show next to a widget, rectangle or global point and keep it on-screen.'''

        self._anchor_target = anchor
        self._anchor_rect = self._resolve_anchor(anchor)
        self._position_for_anchor(self._anchor_rect)
        self.show()
        self.raise_()

    def toggle_for(self, anchor) -> None:
        if self.isVisible():
            self.hide()
        else:
            self.show_for(anchor)

    def reposition(self) -> None:
        if self._anchor_target is not None:
            self._anchor_rect = self._resolve_anchor(self._anchor_target)
        if self._anchor_rect is not None:
            self._position_for_anchor(self._anchor_rect)

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self.dismissed.emit()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            self.hide()
            event.accept()
            return
        super().keyPressEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        palette = self._active_palette
        card = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        painter.setPen(QPen(QColor(palette['border']), 1))
        painter.setBrush(QColor(palette['card']))
        painter.drawRoundedRect(card, 14, 14)

    @staticmethod
    def _resolve_anchor(anchor) -> QRect:
        if isinstance(anchor, QWidget):
            top_left = anchor.mapToGlobal(QPoint(0, 0))
            return QRect(top_left, anchor.size())
        if isinstance(anchor, QRect):
            return QRect(anchor)
        if isinstance(anchor, QPoint):
            return QRect(anchor, anchor)
        raise TypeError('anchor must be a QWidget, QRect or QPoint')

    def _position_for_anchor(self, anchor: QRect) -> None:
        screen = QApplication.screenAt(anchor.center())
        if screen is None:
            screen = QApplication.primaryScreen()
        if screen is None:
            self.move(anchor.left() - self.width() - 10, anchor.top())
            return

        area = screen.availableGeometry()
        gap = 10
        x = anchor.left() - self.width() - gap
        if x < area.left():
            x = anchor.right() + gap
        x = max(area.left(), min(x, area.right() - self.width() + 1))

        y = anchor.bottom() - self.height()
        y = max(area.top(), min(y, area.bottom() - self.height() + 1))
        self.move(x, y)
