"""Full-screen break overlay that covers all monitors."""

import logging

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QKeyEvent, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

log = logging.getLogger(__name__)

_TIPS = [
    "Look at something 20 feet away for 20 seconds.",
    "Close your eyes and relax your eye muscles.",
    "Blink slowly 10 times to re-wet your eyes.",
    "Stand up and stretch your neck and shoulders.",
    "Take a few deep breaths and relax.",
]


class BreakOverlay(QWidget):
    """Semi-transparent overlay shown during breaks."""

    skip_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)

        self._remaining: int = 0
        self._total: int = 0
        self._tip_index: int = 0

        # Countdown timer
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._update_countdown)

        # ---- UI layout ----
        self._title_label = QLabel("Time to rest your eyes\n休息一下眼睛")
        self._title_label.setAlignment(Qt.AlignCenter)
        self._title_label.setFont(QFont("Segoe UI", 28, QFont.Bold))
        self._title_label.setStyleSheet("color: white; background: transparent;")

        self._countdown_label = QLabel("0:00")
        self._countdown_label.setAlignment(Qt.AlignCenter)
        self._countdown_label.setFont(QFont("Segoe UI", 64, QFont.Bold))
        self._countdown_label.setStyleSheet("color: white; background: transparent;")

        self._tip_label = QLabel("")
        self._tip_label.setAlignment(Qt.AlignCenter)
        self._tip_label.setFont(QFont("Segoe UI", 16))
        self._tip_label.setStyleSheet("color: rgba(255,255,255,180); background: transparent;")
        self._tip_label.setWordWrap(True)

        self._skip_btn = QPushButton("Skip")
        self._skip_btn.setFixedSize(120, 40)
        self._skip_btn.setFont(QFont("Segoe UI", 14))
        self._skip_btn.setStyleSheet(
            "QPushButton { color: white; background: rgba(255,255,255,40); "
            "border: 1px solid rgba(255,255,255,80); border-radius: 6px; }"
            "QPushButton:hover { background: rgba(255,255,255,70); }"
        )
        self._skip_btn.clicked.connect(self.skip_requested.emit)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.addStretch()
        layout.addWidget(self._title_label)
        layout.addSpacing(20)
        layout.addWidget(self._countdown_label)
        layout.addSpacing(16)
        layout.addWidget(self._tip_label)
        layout.addSpacing(30)
        layout.addWidget(self._skip_btn, alignment=Qt.AlignCenter)
        layout.addStretch()

    # ---- Public API ----

    def start_break(self, duration_seconds: int, force: bool = True):
        """Show the overlay and start the countdown."""
        self._remaining = duration_seconds
        self._total = duration_seconds
        self._force = force
        self._update_display()
        self._skip_btn.setVisible(not force)

        # Pick a tip
        self._tip_label.setText(_TIPS[self._tip_index % len(_TIPS)])
        self._tip_index += 1

        self._cover_all_screens()
        self.show()
        self.raise_()
        self.activateWindow()
        self._timer.start()
        log.info("Break overlay shown for %ds (force=%s)", duration_seconds, force)

    def end_break(self):
        """Hide the overlay and stop the countdown."""
        self._timer.stop()
        self.hide()
        log.info("Break overlay hidden")

    # ---- Internal ----

    def _update_countdown(self):
        """Tick every second; auto-hide when countdown reaches zero."""
        self._remaining -= 1
        self._update_display()
        if self._remaining <= 0:
            self._timer.stop()
            self.hide()
            log.info("Break countdown finished, overlay auto-hidden")

    def _update_display(self):
        """Refresh the countdown label text."""
        minutes, seconds = divmod(max(0, self._remaining), 60)
        self._countdown_label.setText(f"{minutes}:{seconds:02d}")

    def _cover_all_screens(self):
        """Resize and position the overlay to span all screens."""
        app = QApplication.instance()
        if app is None:
            return
        screens = app.screens()
        if not screens:
            return
        # Compute bounding rect of all screens
        combined = screens[0].geometry()
        for screen in screens[1:]:
            combined = combined.united(screen.geometry())
        self.setGeometry(combined)

    def paintEvent(self, event):
        """Fill background with semi-transparent black."""
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 180))
        painter.end()

    def keyPressEvent(self, event: QKeyEvent):
        """Allow Esc to skip break even in force mode."""
        if event.key() == Qt.Key_Escape:
            self.skip_requested.emit()
        else:
            super().keyPressEvent(event)
