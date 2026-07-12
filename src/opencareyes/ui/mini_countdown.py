"""Small optional floating view of the authoritative break countdown."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

from opencareyes.ui.widgets import first_state_value


class MiniCountdownWidget(QWidget):
    def __init__(self, controller=None, parent=None):
        super().__init__(parent)
        self._controller = controller
        self.setObjectName("miniCountdown")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(148, 68)
        self.setAccessibleName("休息倒计时浮窗")
        self._dragging = False
        self._drag_pos = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(0)
        self._label = QLabel("下次休息")
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setFont(QFont("Segoe UI", 9))
        self._label.setStyleSheet("color: rgba(255,255,255,190); background: transparent;")
        layout.addWidget(self._label)
        self._countdown_label = QLabel("--:--")
        self._countdown_label.setAlignment(Qt.AlignCenter)
        self._countdown_label.setFont(QFont("Segoe UI", 18, QFont.DemiBold))
        self._countdown_label.setStyleSheet("color: white; background: transparent;")
        layout.addWidget(self._countdown_label)

        if controller is not None:
            controller.state_changed.connect(self.render)
            self.render(controller.state)

    def move_to_default(self) -> None:
        app = QApplication.instance()
        screen = app.primaryScreen() if app is not None else None
        if screen is None:
            return
        area = screen.availableGeometry()
        self.move(area.right() - self.width() - 16, area.bottom() - self.height() - 16)

    def update_countdown(self, remaining_seconds: int) -> None:
        minutes, seconds = divmod(max(0, int(remaining_seconds)), 60)
        text = f"{minutes}:{seconds:02d}"
        self._countdown_label.setText(text)
        self.setAccessibleDescription(f"距离下次休息 {minutes} 分 {seconds} 秒")

    def set_break_mode(self) -> None:
        self._label.setText("休息中")
        self._countdown_label.setText("放松眼睛")
        self.setAccessibleDescription("当前正在休息")

    def render(self, state) -> None:
        enabled = bool(first_state_value(state, "breaks.enabled", default=False))
        phase = str(first_state_value(state, "breaks.phase", default="stopped"))
        paused = bool(first_state_value(state, "breaks.paused", default=False))
        remaining = int(first_state_value(state, "breaks.remaining", default=0))
        display_mode = str(first_state_value(
            state, "breaks.countdown_display", default="tray"
        ))
        if not enabled or display_mode != "floating":
            self.hide()
            return
        if phase == "resting":
            self._label.setText("休息中")
            self.update_countdown(remaining)
        elif paused:
            self._label.setText("计时已暂停")
            self.update_countdown(remaining)
        else:
            self._label.setText("下次休息")
            self.update_countdown(remaining)
        if not self.isVisible():
            self.move_to_default()
            self.show()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QColor(22, 26, 35, 225))
        painter.setPen(QColor(255, 255, 255, 28))
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 12, 12)
        painter.end()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._dragging = True
            self._drag_pos = event.globalPosition().toPoint() - self.pos()
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._dragging and self._drag_pos is not None:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._dragging = False
            self._drag_pos = None
            event.accept()
