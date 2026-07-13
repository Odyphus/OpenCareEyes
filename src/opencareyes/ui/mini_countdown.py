"""Optional always-on-top countdown companion."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from opencareyes.ui.widgets import first_state_value


_MOOD_COLORS = {
    "working": QColor("#5B8DEF"),
    "resting": QColor("#58B891"),
    "paused": QColor("#7D8799"),
}


class _PetFace(QWidget):
    """Small original mascot drawn with Qt primitives."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mood = "working"
        self.setFixedSize(82, 88)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAccessibleName("护眼倒计时小伙伴")

    @property
    def mood(self) -> str:
        return self._mood

    def set_mood(self, mood: str) -> None:
        selected = mood if mood in _MOOD_COLORS else "working"
        if selected != self._mood:
            self._mood = selected
            self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        accent = _MOOD_COLORS[self._mood]
        body = QRectF(10, 20, 62, 57)

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 48))
        painter.drawRoundedRect(body.translated(0, 3), 18, 18)
        painter.setPen(QPen(QColor(255, 255, 255, 80), 1.2))
        painter.setBrush(accent)
        painter.drawRoundedRect(body, 18, 18)

        # A warm sprout makes the character distinctive without relying on an
        # external mascot asset.
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#F2A65A"))
        painter.drawEllipse(QRectF(34, 8, 13, 16))
        painter.setBrush(QColor("#F7C77F"))
        painter.drawEllipse(QRectF(43, 11, 12, 10))

        eye_pen = QPen(QColor("#101827"), 3.2, Qt.SolidLine, Qt.RoundCap)
        painter.setPen(eye_pen)
        if self._mood == "resting":
            painter.drawLine(26, 47, 33, 47)
            painter.drawLine(49, 47, 56, 47)
        else:
            painter.drawPoint(30, 47)
            painter.drawPoint(52, 47)

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(255, 137, 153, 155))
        painter.drawEllipse(QRectF(19, 54, 8, 5))
        painter.drawEllipse(QRectF(55, 54, 8, 5))

        mouth = QPainterPath()
        if self._mood == "paused":
            mouth.moveTo(37, 60)
            mouth.lineTo(45, 60)
        elif self._mood == "resting":
            mouth.moveTo(36, 59)
            mouth.cubicTo(39, 62, 43, 62, 46, 59)
        else:
            mouth.moveTo(36, 58)
            mouth.cubicTo(39, 64, 43, 64, 46, 58)
        painter.setPen(QPen(QColor("#101827"), 2, Qt.SolidLine, Qt.RoundCap))
        painter.drawPath(mouth)

        painter.setPen(QPen(accent.lighter(135), 3, Qt.SolidLine, Qt.RoundCap))
        painter.drawLine(24, 79, 32, 79)
        painter.drawLine(50, 79, 58, 79)
        painter.end()


class MiniCountdownWidget(QWidget):
    """Draggable countdown pet backed by the authoritative break state."""

    def __init__(self, controller=None, parent=None):
        super().__init__(parent)
        self._controller = controller
        self._mood = "working"
        self._dragging = False
        self._drag_pos = None
        self._positioned = False

        self.setObjectName("miniCountdown")
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedSize(242, 112)
        self.setAccessibleName("休息倒计时桌宠")
        self.setToolTip("拖动桌宠可调整位置；点击右上角可隐藏")

        self._build_ui()

        if controller is not None:
            controller.state_changed.connect(self.render)
            self.render(controller.state)

    @property
    def mood(self) -> str:
        return self._mood

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 10, 10)
        layout.setSpacing(8)

        self._pet = _PetFace(self)
        layout.addWidget(self._pet)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 15, 0, 13)
        text_layout.setSpacing(1)

        self._label = QLabel("距离下次休息")
        self._label.setFont(QFont("Microsoft YaHei UI", 9))
        self._label.setStyleSheet(
            "color: rgba(235,241,252,205); background: transparent;"
        )
        self._label.setAttribute(Qt.WA_TransparentForMouseEvents)
        text_layout.addWidget(self._label)

        self._countdown_label = QLabel("--:--")
        self._countdown_label.setFont(
            QFont("Microsoft YaHei UI", 23, QFont.DemiBold)
        )
        self._countdown_label.setStyleSheet(
            "color: white; background: transparent;"
        )
        self._countdown_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        text_layout.addWidget(self._countdown_label)

        self._hint_label = QLabel("护眼小伙伴正在陪你")
        self._hint_label.setFont(QFont("Microsoft YaHei UI", 8))
        self._hint_label.setStyleSheet(
            "color: rgba(187,199,220,180); background: transparent;"
        )
        self._hint_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        text_layout.addWidget(self._hint_label)
        layout.addLayout(text_layout, 1)

        close_layout = QVBoxLayout()
        close_layout.setContentsMargins(0, 1, 0, 0)
        self._close_button = QToolButton(self)
        self._close_button.setText("×")
        self._close_button.setFixedSize(24, 24)
        self._close_button.setCursor(Qt.PointingHandCursor)
        self._close_button.setAccessibleName("隐藏倒计时桌宠")
        self._close_button.setToolTip("隐藏桌宠，可在休息节奏中重新开启")
        self._close_button.setStyleSheet(
            "QToolButton { color: rgba(235,241,252,190); "
            "background: rgba(255,255,255,12); border: none; "
            "border-radius: 12px; font-size: 17px; }"
            "QToolButton:hover, QToolButton:focus { color: white; "
            "background: rgba(255,255,255,34); }"
        )
        self._close_button.clicked.connect(self.hide_pet)
        close_layout.addWidget(self._close_button)
        close_layout.addStretch()
        layout.addLayout(close_layout)

    def move_to_default(self) -> None:
        app = QApplication.instance()
        screen = app.primaryScreen() if app is not None else None
        if screen is None:
            return
        area = screen.availableGeometry()
        self.move(area.right() - self.width() - 18, area.bottom() - self.height() - 18)
        self._positioned = True

    def update_countdown(self, remaining_seconds: int) -> None:
        minutes, seconds = divmod(max(0, int(remaining_seconds)), 60)
        self._countdown_label.setText(f"{minutes}:{seconds:02d}")
        self.setAccessibleDescription(
            f"{self._label.text()}，剩余 {minutes} 分 {seconds} 秒"
        )

    def set_break_mode(self) -> None:
        self._set_mood("resting")
        self._label.setText("休息时间")
        self._hint_label.setText("看看远处，慢慢放松")
        self._countdown_label.setText("放松一下")
        self.setAccessibleDescription("当前正在休息")

    def hide_pet(self) -> None:
        self.hide()
        if self._controller is not None:
            self._controller.set_break_countdown_display("tray")

    def render(self, state) -> None:
        enabled = bool(first_state_value(state, "breaks.enabled", default=False))
        phase = str(first_state_value(state, "breaks.phase", default="stopped"))
        paused = bool(first_state_value(state, "breaks.paused", default=False))
        remaining = int(first_state_value(state, "breaks.remaining", default=0))
        display_mode = str(
            first_state_value(state, "breaks.countdown_display", default="tray")
        )

        if not enabled or display_mode != "floating":
            self.hide()
            return

        if paused:
            self._set_mood("paused")
            self._label.setText(
                "休息已暂停" if phase == "resting" else "计时已暂停"
            )
            self._hint_label.setText(
                "继续后完成剩余休息" if phase == "resting" else "准备好后再继续"
            )
        elif phase == "resting":
            self._set_mood("resting")
            self._label.setText("休息时间")
            self._hint_label.setText("看看远处，慢慢放松")
        else:
            self._set_mood("working")
            self._label.setText("距离下次休息")
            self._hint_label.setText("护眼小伙伴正在陪你")

        self.update_countdown(remaining)
        if not self.isVisible():
            if not self._positioned:
                self.move_to_default()
            self.show()

    def _set_mood(self, mood: str) -> None:
        self._mood = mood if mood in _MOOD_COLORS else "working"
        self._pet.set_mood(self._mood)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        card = QRectF(4, 3, self.width() - 8, self.height() - 10)

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 72))
        painter.drawRoundedRect(card.translated(0, 4), 18, 18)
        painter.setPen(QPen(QColor(255, 255, 255, 30), 1))
        painter.setBrush(QColor(17, 23, 36, 242))
        painter.drawRoundedRect(card, 18, 18)

        accent = _MOOD_COLORS[self._mood]
        painter.setPen(Qt.NoPen)
        painter.setBrush(accent)
        painter.drawRoundedRect(
            QRectF(18, self.height() - 10, self.width() - 36, 3),
            1.5,
            1.5,
        )
        painter.end()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._dragging = True
            self._drag_pos = event.globalPosition().toPoint() - self.pos()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._dragging and self._drag_pos is not None:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            self._positioned = True
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._dragging = False
            self._drag_pos = None
            event.accept()
        else:
            super().mouseReleaseEvent(event)
