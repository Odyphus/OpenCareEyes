"""Software screen dimming via transparent overlays."""

import logging

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QScreen
from PySide6.QtWidgets import QApplication, QWidget

from opencareyes.platform.win32_api import (
    GWL_EXSTYLE,
    WS_EX_LAYERED,
    WS_EX_TRANSPARENT,
    WS_EX_TOOLWINDOW,
    GetWindowLongW,
    SetWindowLongW,
)

log = logging.getLogger(__name__)


def _make_click_through(widget: QWidget):
    """Force Win32 WS_EX_TRANSPARENT so the window passes all mouse input."""
    hwnd = int(widget.winId())
    if not hwnd:
        return
    ex_style = GetWindowLongW(hwnd, GWL_EXSTYLE)
    SetWindowLongW(
        hwnd, GWL_EXSTYLE,
        ex_style | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW,
    )


class DimOverlay(QWidget):
    """Full-screen transparent overlay for software dimming."""

    def __init__(self, screen: QScreen):
        super().__init__()
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setGeometry(screen.geometry())
        self._opacity = 0

    def showEvent(self, event):
        """After the window is shown, apply Win32 click-through."""
        super().showEvent(event)
        _make_click_through(self)

    def set_dim_level(self, level: int):
        """Set dim level (0=no dim, 200=max dim)."""
        self._opacity = max(0, min(200, level))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, self._opacity))
        painter.end()


class ScreenDimmer:
    """Manages DimOverlay instances across all screens."""

    def __init__(self):
        self._overlays: list[DimOverlay] = []
        self._enabled = False
        self._dim_level = 0

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def dim_level(self) -> int:
        return self._dim_level

    def enable(self, level: int = 100):
        """Create overlays for all screens and show them."""
        if self._enabled:
            self.set_brightness(level)
            return
        self._dim_level = level
        self._create_overlays()
        for overlay in self._overlays:
            overlay.set_dim_level(level)
            overlay.show()
        self._enabled = True
        log.info("Screen dimmer enabled at level %d", level)

    def disable(self):
        """Hide and remove all overlays."""
        for overlay in self._overlays:
            overlay.hide()
            overlay.close()
            overlay.deleteLater()
        self._overlays.clear()
        self._enabled = False
        self._dim_level = 0
        log.info("Screen dimmer disabled")

    def set_brightness(self, level: int):
        """Update dim level on all overlays."""
        self._dim_level = max(0, min(200, level))
        for overlay in self._overlays:
            overlay.set_dim_level(self._dim_level)

    def refresh_screens(self):
        """Recreate overlays when screen configuration changes."""
        was_enabled = self._enabled
        saved_level = self._dim_level
        if was_enabled:
            self.disable()
            self.enable(saved_level)

    def _create_overlays(self):
        """Create one overlay per screen."""
        app = QApplication.instance()
        if app is None:
            log.warning("No QApplication instance; cannot create overlays")
            return
        for screen in app.screens():
            overlay = DimOverlay(screen)
            self._overlays.append(overlay)
