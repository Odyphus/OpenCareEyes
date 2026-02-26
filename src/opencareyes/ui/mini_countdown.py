"""Mini floating countdown widget for break reminder."""

import logging

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout

log = logging.getLogger(__name__)


class MiniCountdownWidget(QWidget):
    """Small draggable floating widget showing countdown to next break."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(140, 60)

        # Dragging state
        self._dragging = False
        self._drag_pos = None

        # UI
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        self._label = QLabel("下次休息")
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setFont(QFont("Segoe UI", 9))
        self._label.setStyleSheet("color: white; background: transparent;")
        layout.addWidget(self._label)

        self._countdown_label = QLabel("--:--")
        self._countdown_label.setAlignment(Qt.AlignCenter)
        self._countdown_label.setFont(QFont("Segoe UI", 18, QFont.Bold))
        self._countdown_label.setStyleSheet("color: white; background: transparent;")
        layout.addWidget(self._countdown_label)

    def update_countdown(self, remaining_seconds: int):
        """Update the countdown display."""
        minutes, seconds = divmod(remaining_seconds, 60)
        self._countdown_label.setText(f"{minutes}:{seconds:02d}")

    def set_break_mode(self):
        """Show 'resting' state."""
        self._countdown_label.setText("休息中")

    def paintEvent(self, event):
        """Draw rounded semi-transparent background."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QColor(30, 30, 46, 200))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(self.rect(), 8, 8)
        painter.end()

    def mousePressEvent(self, event):
        """Start dragging."""
        if event.button() == Qt.LeftButton:
            self._dragging = True
            self._drag_pos = event.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, event):
        """Handle dragging."""
        if self._dragging and self._drag_pos:
            self.move(event.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, event):
        """Stop dragging."""
        if event.button() == Qt.LeftButton:
            self._dragging = False
