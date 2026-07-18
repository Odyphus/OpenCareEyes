"""Non-blocking progressive break prompt."""

from __future__ import annotations

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QColor, QKeyEvent, QPainter, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from opencareyes.ui.widgets import first_state_value


class _UndoToast(QWidget):
    undo_clicked = Signal()

    def __init__(self):
        super().__init__(None)
        self._theme_signature = None
        self._theme_colors: dict[str, str] = {}
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setObjectName("undoToast")
        self.setAccessibleName("休息提醒已延后，可撤销")
        self.setFixedSize(360, 76)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 12, 14, 12)
        self._label = QLabel("已延后 5 分钟 · 不计入活跃用眼")
        self._label.setAccessibleName("延后结果")
        self._undo = QPushButton("撤销")
        self._undo.setObjectName("secondaryButton")
        self._undo.setAccessibleName("撤销稍后提醒")
        self._undo.setFocusPolicy(Qt.StrongFocus)
        self._undo.clicked.connect(self.undo_clicked)
        layout.addWidget(self._label, 1)
        layout.addWidget(self._undo)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(8000)
        self._timer.timeout.connect(self.hide)
        app = QApplication.instance()
        self.apply_theme(getattr(app, "theme_snapshot", None))

    def apply_theme(self, snapshot) -> None:
        resolved = str(getattr(snapshot, "resolved", "dark"))
        resolved = resolved if resolved in {"light", "dark"} else "dark"
        high_contrast = bool(getattr(snapshot, "high_contrast", False))
        signature = (resolved, high_contrast)
        if signature == self._theme_signature:
            return
        self._theme_signature = signature
        self.setProperty("highContrast", high_contrast)
        if high_contrast:
            palette = QApplication.palette()
            colors = {
                "card": palette.color(QPalette.Window).name(),
                "text": palette.color(QPalette.WindowText).name(),
                "border": palette.color(QPalette.Mid).name(),
                "button": palette.color(QPalette.Button).name(),
                "button_text": palette.color(QPalette.ButtonText).name(),
                "focus": palette.color(QPalette.Highlight).name(),
            }
        elif resolved == "light":
            colors = {
                "card": "#FFFFFF", "text": "#172033", "border": "#CAD5E5",
                "button": "#EAF0FA", "button_text": "#172033", "focus": "#365FBD",
            }
        else:
            colors = {
                "card": "#172033", "text": "#F7FAFF", "border": "#3A4963",
                "button": "#253149", "button_text": "#F7FAFF", "focus": "#8FB2FF",
            }
        self._theme_colors = colors
        self.setStyleSheet(
            "QWidget#undoToast { "
            f"background: {colors['card']}; border: 1px solid {colors['border']}; "
            "border-radius: 12px; } "
            f"QLabel {{ color: {colors['text']}; background: transparent; }} "
            "QPushButton { border-radius: 8px; padding: 6px 12px; "
            f"background: {colors['button']}; color: {colors['button_text']}; "
            f"border: 1px solid {colors['border']}; }} "
            f"QPushButton:focus {{ border: 2px solid {colors['focus']}; }}"
        )

    def show_toast(self) -> None:
        app = QApplication.instance()
        screen = app.primaryScreen() if app is not None else None
        if screen is not None:
            area = screen.availableGeometry()
            self.move(
                area.right() - self.width() - 20,
                area.bottom() - self.height() - 20,
            )
        self.show()
        self.raise_()
        self._timer.start()


class BreakPrompt(QWidget):
    """A corner card that asks before a progressive rest countdown starts."""

    start_requested = Signal()
    snooze_requested = Signal(int)
    skip_requested = Signal()
    undo_requested = Signal()

    def __init__(self, controller=None, parent=None):
        super().__init__(parent)
        self._controller = controller
        self._kind = "short"
        self._stage = "gentle"
        self._handling_action = False
        self._theme_signature = None
        self._theme_colors: dict[str, str] = {}
        self.setObjectName("breakPrompt")
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAccessibleName("温和休息提醒")
        self.setFixedSize(410, 224)
        self._build_ui()
        self._undo_toast = _UndoToast()
        self._undo_toast.undo_clicked.connect(self._undo_snooze)
        app = QApplication.instance()
        self.apply_theme(getattr(app, "theme_snapshot", None))

        if controller is not None:
            start = getattr(controller, "start_due_break", None)
            if start is not None:
                self.start_requested.connect(start)
            snooze = getattr(controller, "snooze_break", None)
            if snooze is not None:
                self.snooze_requested.connect(snooze)
            skip = getattr(controller, "skip_break", None)
            if skip is not None:
                self.skip_requested.connect(skip)
            undo = getattr(controller, "undo_break_snooze", None)
            if undo is not None:
                self.undo_requested.connect(undo)
            controller.state_changed.connect(self.render)
            self.render(controller.state)

    @property
    def kind(self) -> str:
        return self._kind

    @property
    def stage(self) -> str:
        return self._stage

    def _build_ui(self) -> None:
        self._title = QLabel("该让眼睛休息一下了")
        self._title.setObjectName("promptTitle")
        self._title.setAccessibleName("休息提醒标题")
        self._title.setStyleSheet(
            "color: white; background: transparent; font-size: 19px; font-weight: 600;"
        )
        self._message = QLabel("现在停一下，看看远处，让眼睛慢慢放松。")
        self._message.setWordWrap(True)
        self._message.setAccessibleName("休息提醒说明")
        self._message.setStyleSheet(
            "color: rgba(255,255,255,205); background: transparent; font-size: 13px;"
        )

        self._close = QToolButton()
        self._close.setText("×")
        self._close.setFixedSize(28, 28)
        self._close.setAccessibleName("关闭并在 5 分钟后提醒")
        self._close.setToolTip("关闭后将在 5 分钟后再次提醒")
        self._close.setFocusPolicy(Qt.StrongFocus)
        self._close.setStyleSheet(
            "QToolButton { color: rgba(255,255,255,190); background: transparent; "
            "border: none; border-radius: 14px; font-size: 18px; }"
            "QToolButton:hover { color: white; background: rgba(255,255,255,25); }"
        )
        self._close.clicked.connect(lambda: self._snooze(5))

        title_row = QHBoxLayout()
        title_row.addWidget(self._title)
        title_row.addStretch()
        title_row.addWidget(self._close)

        self._start = QPushButton("现在休息")
        self._start.setObjectName("primaryButton")
        self._start.setAccessibleName("现在开始休息")
        self._start.setFocusPolicy(Qt.StrongFocus)
        self._start.clicked.connect(self._start_break)

        self._snooze_button = QToolButton()
        self._snooze_button.setText("稍后提醒")
        self._snooze_button.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(self._snooze_button)
        menu.setAccessibleName("稍后提醒时间")
        for minutes in (5, 10, 30):
            action = menu.addAction(f"{minutes} 分钟后提醒")
            action.triggered.connect(
                lambda checked=False, value=minutes: self._snooze(value)
            )
        self._snooze_button.setMenu(menu)
        self._snooze_button.setAccessibleName("选择稍后提醒时间")
        self._snooze_button.setFocusPolicy(Qt.StrongFocus)

        self._skip = QPushButton("本次跳过")
        self._skip.setObjectName("quietButton")
        self._skip.setAccessibleName("跳过本次休息并重置当前周期")
        self._skip.setFocusPolicy(Qt.StrongFocus)
        self._skip.clicked.connect(self._skip_break)

        actions = QHBoxLayout()
        actions.addWidget(self._start)
        actions.addWidget(self._snooze_button)
        actions.addWidget(self._skip)
        actions.addStretch()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 22)
        layout.setSpacing(13)
        layout.addLayout(title_row)
        layout.addWidget(self._message)
        layout.addStretch()
        layout.addLayout(actions)

    def apply_theme(self, snapshot) -> None:
        """Apply the shared theme to the prompt and its undo notice."""

        resolved = str(getattr(snapshot, "resolved", "dark"))
        resolved = resolved if resolved in {"light", "dark"} else "dark"
        high_contrast = bool(getattr(snapshot, "high_contrast", False))
        signature = (resolved, high_contrast)
        if signature == self._theme_signature:
            self._undo_toast.apply_theme(snapshot)
            return
        self._theme_signature = signature
        self.setProperty("highContrast", high_contrast)
        if high_contrast:
            palette = QApplication.palette()
            colors = {
                "card": palette.color(QPalette.Window).name(),
                "prominent": palette.color(QPalette.Window).name(),
                "text": palette.color(QPalette.WindowText).name(),
                "muted": palette.color(QPalette.Text).name(),
                "border": palette.color(QPalette.Mid).name(),
                "button": palette.color(QPalette.Button).name(),
                "button_text": palette.color(QPalette.ButtonText).name(),
                "primary": palette.color(QPalette.Highlight).name(),
                "primary_text": palette.color(QPalette.HighlightedText).name(),
                "focus": palette.color(QPalette.Highlight).name(),
                "accent": palette.color(QPalette.Highlight).name(),
                "shadow": palette.color(QPalette.Shadow).name(),
            }
        elif resolved == "light":
            colors = {
                "card": "#F8FBFF", "prominent": "#EEF3FC", "text": "#172033",
                "muted": "#58677F", "border": "#CAD5E5", "button": "#EAF0FA",
                "button_text": "#172033", "primary": "#5B8DEF",
                "primary_text": "#FFFFFF", "focus": "#365FBD",
                "accent": "#F2A65A", "shadow": "#71809A",
            }
        else:
            colors = {
                "card": "#172033", "prominent": "#29354D", "text": "#F7FAFF",
                "muted": "#C4CFE1", "border": "#3A4963", "button": "#253149",
                "button_text": "#F7FAFF", "primary": "#5B8DEF",
                "primary_text": "#FFFFFF", "focus": "#8FB2FF",
                "accent": "#F2A65A", "shadow": "#000000",
            }
        self._theme_colors = colors
        self._title.setStyleSheet(
            f"color: {colors['text']}; background: transparent; "
            "font-size: 19px; font-weight: 600;"
        )
        self._message.setStyleSheet(
            f"color: {colors['muted']}; background: transparent; font-size: 13px;"
        )
        self._close.setStyleSheet(
            "QToolButton { background: transparent; border: 1px solid transparent; "
            f"color: {colors['muted']}; border-radius: 14px; font-size: 18px; }} "
            f"QToolButton:hover {{ background: {colors['button']}; color: {colors['text']}; }} "
            f"QToolButton:focus {{ border: 2px solid {colors['focus']}; }}"
        )
        secondary_style = (
            "QPushButton, QToolButton { border-radius: 8px; padding: 7px 12px; "
            f"background: {colors['button']}; color: {colors['button_text']}; "
            f"border: 1px solid {colors['border']}; }} "
            f"QPushButton:hover, QToolButton:hover {{ border-color: {colors['focus']}; }} "
            f"QPushButton:focus, QToolButton:focus {{ border: 2px solid {colors['focus']}; }}"
        )
        self._snooze_button.setStyleSheet(secondary_style)
        self._skip.setStyleSheet(secondary_style)
        self._start.setStyleSheet(
            "QPushButton { border-radius: 8px; padding: 7px 12px; "
            f"background: {colors['primary']}; color: {colors['primary_text']}; "
            f"border: 1px solid {colors['primary']}; }} "
            f"QPushButton:focus {{ border: 2px solid {colors['focus']}; }}"
        )
        menu = self._snooze_button.menu()
        if menu is not None:
            menu.setStyleSheet(
                f"QMenu {{ background: {colors['card']}; color: {colors['text']}; "
                f"border: 1px solid {colors['border']}; }} "
                f"QMenu::item:selected {{ background: {colors['primary']}; "
                f"color: {colors['primary_text']}; }}"
            )
        self._undo_toast.apply_theme(snapshot)
        self.update()

    def show_prompt(self, kind: str = "short", stage: str = "gentle") -> None:
        self._start.show()
        self._snooze_button.show()
        self._skip.show()
        self._kind = "long" if kind == "long" else "short"
        self._stage = "prominent" if stage == "prominent" else "gentle"
        if self._kind == "long":
            self._title.setText("该进行一次长休息了")
            self._message.setText("你已经专注了一段时间。站起来活动一下，再看看远处。")
        else:
            self._title.setText("该让眼睛休息一下了")
            self._message.setText("现在停一下，看看远处，让眼睛慢慢放松。")
        if self._stage == "prominent":
            self.setAccessibleName("需要处理的休息提醒")
            self.setFixedSize(430, 238)
        else:
            self.setAccessibleName("温和休息提醒")
            self.setFixedSize(410, 224)
        self._position_at_corner()
        if not self.isVisible():
            # WA_ShowWithoutActivating keeps the user's editor in front of the
            # keyboard focus while the card becomes visible.
            self.show()
        self.raise_()

    def render(self, state) -> None:
        enabled = bool(first_state_value(state, "breaks.enabled", default=False))
        phase = str(first_state_value(state, "breaks.phase", default="stopped"))
        force = bool(first_state_value(state, "breaks.force_break", default=False))
        style = str(
            first_state_value(
                state,
                "breaks.reminder_style",
                "breaks.prompt_style",
                default="fullscreen",
            )
        )
        display_mode = str(
            first_state_value(state, "breaks.countdown_display", default="tray")
        )
        kind = str(
            first_state_value(
                state,
                "break_prompt.kind",
                "breaks.prompt.kind",
                "breaks.due_kind",
                "breaks.current_break_kind",
                default="short",
            )
        )
        stage = str(
            first_state_value(
                state,
                "break_prompt.stage",
                "breaks.prompt.stage",
                "breaks.prompt_stage",
                default="none",
            )
        )
        suppressed = tuple(
            first_state_value(
                state,
                "effective_policy.breaks.suppressed_by",
                default=(),
            )
            or ()
        )
        if not enabled or suppressed:
            self._undo_toast.hide()
        if (
            enabled
            and phase == "prompting"
            and style == "progressive"
            and display_mode != "floating"
            and not force
            and not suppressed
            and stage in {"gentle", "prominent"}
        ):
            self.show_prompt(kind, stage)
        else:
            self.hide()

    def _start_break(self) -> None:
        self._handling_action = True
        self.hide()
        self.start_requested.emit()
        self._handling_action = False

    def _snooze(self, minutes: int) -> None:
        self._handling_action = True
        self.hide()
        self.snooze_requested.emit(max(1, int(minutes)))
        self._handling_action = False
        if int(minutes) == 5:
            self._show_undo_notice()

    def _skip_break(self) -> None:
        self._handling_action = True
        self.hide()
        self.skip_requested.emit()
        self._handling_action = False

    def _show_undo_notice(self) -> None:
        self._undo_toast.show_toast()

    def _undo_snooze(self) -> None:
        self._undo_toast.hide()
        self.undo_requested.emit()

    def _dismiss_undo(self) -> None:
        self._undo_toast.hide()

    def _position_at_corner(self) -> None:
        app = QApplication.instance()
        screen = app.primaryScreen() if app is not None else None
        if screen is None:
            return
        area = screen.availableGeometry()
        self.move(
            area.right() - self.width() - 20,
            area.bottom() - self.height() - 20,
        )

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        card = self.rect().adjusted(4, 3, -4, -8)
        colors = self._theme_colors
        shadow = QColor(colors.get("shadow", "#000000"))
        shadow.setAlpha(62)
        painter.setPen(Qt.NoPen)
        painter.setBrush(shadow)
        painter.drawRoundedRect(card.translated(0, 4), 18, 18)
        painter.setPen(QColor(colors.get("border", "#3A4963")))
        card_color = colors.get("prominent" if self._stage == "prominent" else "card")
        painter.setBrush(QColor(card_color or "#172033"))
        painter.drawRoundedRect(card, 18, 18)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(colors.get("accent", "#F2A65A")))
        painter.drawRoundedRect(card.adjusted(16, card.height() - 4, -16, -1), 2, 2)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key_Escape:
            self._snooze(5)
            event.accept()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event) -> None:
        if self.isVisible() and not self._handling_action:
            event.ignore()
            self._snooze(5)
            return
        super().closeEvent(event)
