'''Independent quick-action bubble shown beside the desktop companion.'''

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QRectF, Signal, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPalette, QPen
from PySide6.QtWidgets import (
    QApplication,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
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
    start_due_requested = Signal()
    snooze_requested = Signal(int)
    skip_requested = Signal()
    dismissed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._theme = 'dark'
        self._high_contrast = False
        self._theme_signature = None
        self._active_palette = dict(_THEMES['dark'])
        self._anchor_rect: QRect | None = None
        self._anchor_target = None
        self._mode = ''
        self._focusable = False

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

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def is_rest_prompt_active(self) -> bool:
        return self._mode == 'rest_prompt'

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
        self._close.setFocusPolicy(Qt.StrongFocus)
        self._close.clicked.connect(self._close_requested)
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

        self._tools_widget = QWidget(self)
        tools = QGridLayout(self._tools_widget)
        tools.setContentsMargins(0, 0, 0, 0)
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
            button.setFocusPolicy(Qt.StrongFocus)
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
            button.setFocusPolicy(Qt.StrongFocus)
            button.clicked.connect(
                lambda _checked=False, selected=item_id: self.item_requested.emit(
                    selected
                )
            )
            tools.addWidget(button, 1, column)
            self._item_buttons[item_id] = button
        layout.addWidget(self._tools_widget)

        self._rest_actions_widget = QWidget(self)
        rest_actions = QHBoxLayout(self._rest_actions_widget)
        rest_actions.setContentsMargins(0, 0, 0, 0)
        rest_actions.setSpacing(8)

        self._start_due_button = QPushButton('现在休息')
        self._start_due_button.setCursor(Qt.PointingHandCursor)
        self._start_due_button.setAccessibleName('现在开始本次休息')
        self._start_due_button.setFocusPolicy(Qt.StrongFocus)
        self._start_due_button.clicked.connect(self._request_start_due)
        rest_actions.addWidget(self._start_due_button)

        self._snooze_button = QToolButton(self)
        self._snooze_button.setText('稍后提醒')
        self._snooze_button.setPopupMode(QToolButton.InstantPopup)
        self._snooze_button.setCursor(Qt.PointingHandCursor)
        self._snooze_button.setAccessibleName('选择稍后提醒时间')
        self._snooze_button.setFocusPolicy(Qt.StrongFocus)
        self._snooze_menu = QMenu(self._snooze_button)
        self._snooze_menu.setAccessibleName('稍后提醒时间')
        self._snooze_actions = {}
        for minutes in (5, 10, 30):
            action = self._snooze_menu.addAction(f'{minutes} 分钟')
            action.triggered.connect(
                lambda _checked=False, value=minutes: self._request_snooze(value)
            )
            self._snooze_actions[minutes] = action
        self._snooze_button.setMenu(self._snooze_menu)
        rest_actions.addWidget(self._snooze_button)

        self._skip_button = QPushButton('本次跳过')
        self._skip_button.setCursor(Qt.PointingHandCursor)
        self._skip_button.setAccessibleName('跳过本次休息提醒')
        self._skip_button.setFocusPolicy(Qt.StrongFocus)
        self._skip_button.clicked.connect(self._request_skip)
        rest_actions.addWidget(self._skip_button)
        layout.addWidget(self._rest_actions_widget)
        self._set_mode('quick')

    def set_status(self, title: str, detail: str = '') -> None:
        if self.is_rest_prompt_active:
            return
        self._title.setText(str(title))
        self._detail.setText(str(detail))

    def show_rest_prompt(
        self,
        anchor,
        *,
        title: str = '该休息一下眼睛了',
        detail: str = '看看远处，让眼睛放松一下。',
    ) -> None:
        self._set_mode('rest_prompt')
        self._title.setText(str(title))
        self._detail.setText(str(detail))
        self.show_for(anchor)

    def clear_rest_prompt(self) -> None:
        if self.is_rest_prompt_active:
            self._set_mode('quick')
            self.hide()

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

    def apply_theme(self, snapshot) -> None:
        '''Compatibility entry point shared by all themed companion surfaces.'''

        self.set_theme(snapshot)

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
            'QToolButton { border: 1px solid transparent; border-radius: 12px; background: transparent; '
            f'color: {text_color}; font-size: 17px; }} '
            f'QToolButton:hover {{ background: {button_color}; }} '
            f'QToolButton:focus {{ border: 2px solid {hover_color}; }}'
        )
        button_style = (
            'QPushButton, QToolButton { border: 1px solid transparent; border-radius: 8px; '
            f'padding: 6px 8px; background: {button_color}; color: {title_color}; }} '
            f'QPushButton:hover, QToolButton:hover {{ background: {hover_color}; }} '
            f'QPushButton:focus, QToolButton:focus {{ border: 2px solid {hover_color}; }}'
        )
        for button in (
            *self._tool_buttons.values(),
            *self._item_buttons.values(),
            self._start_due_button,
            self._snooze_button,
            self._skip_button,
        ):
            button.setStyleSheet(button_style)
        self._snooze_menu.setStyleSheet(
            f'QMenu {{ background: {palette["card"]}; color: {title_color}; '
            f'border: 1px solid {palette["border"]}; }} '
            f'QMenu::item:selected {{ background: {hover_color}; }}'
        )
        self.update()

    def show_for(self, anchor, *, focusable: bool = False) -> None:
        '''Show next to a widget, rectangle or global point and keep it on-screen.'''

        self._focusable = bool(focusable)
        self.setAttribute(Qt.WA_ShowWithoutActivating, not self._focusable)
        self._anchor_target = anchor
        self._anchor_rect = self._resolve_anchor(anchor)
        self._position_for_anchor(self._anchor_rect)
        self.show()
        self.raise_()
        if self._focusable:
            self.activateWindow()
            self._first_focus_target().setFocus(Qt.TabFocusReason)

    def toggle_for(self, anchor, *, focusable: bool = False) -> None:
        if self.isVisible():
            if self.is_rest_prompt_active:
                self._request_snooze(5)
            else:
                self.hide()
        else:
            self._set_mode('quick')
            self.show_for(anchor, focusable=focusable)

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
            if self.is_rest_prompt_active:
                self._request_snooze(5)
            else:
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

    def _set_mode(self, mode: str) -> None:
        mode = 'rest_prompt' if str(mode) == 'rest_prompt' else 'quick'
        if mode == self._mode:
            return
        self._mode = mode
        is_rest_prompt = mode == 'rest_prompt'
        self._tools_widget.setVisible(not is_rest_prompt)
        self._rest_actions_widget.setVisible(is_rest_prompt)

    def _first_focus_target(self) -> QWidget:
        if self.is_rest_prompt_active:
            return self._start_due_button
        for button in self._tool_buttons.values():
            if not button.isHidden() and button.isEnabled():
                return button
        return self._close

    def _request_start_due(self) -> None:
        self.start_due_requested.emit()
        self._set_mode('quick')
        self.hide()

    def _request_snooze(self, minutes: int) -> None:
        self.snooze_requested.emit(max(1, int(minutes)))
        self._set_mode('quick')
        self.hide()

    def _request_skip(self) -> None:
        self.skip_requested.emit()
        self._set_mode('quick')
        self.hide()

    def _close_requested(self) -> None:
        if self.is_rest_prompt_active:
            self._request_snooze(5)
        else:
            self.hide()
