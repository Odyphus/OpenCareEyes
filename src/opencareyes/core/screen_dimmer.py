"""Software screen dimming via transparent overlays."""

import logging

from PySide6.QtCore import QObject, Qt, Signal
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
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
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


class ScreenDimmer(QObject):
    """Manages DimOverlay instances across all screens."""

    operation_failed = Signal(str, str)

    def __init__(self, *, watch_screen_events: bool = True):
        super().__init__()
        self._overlays: list[DimOverlay] = []
        self._enabled = False
        self._dim_level = 0
        self._last_error_code = ""
        self._last_error_message = ""
        self._watched_screens: set[int] = set()
        app = QApplication.instance()
        if app is not None and watch_screen_events:
            for screen in app.screens():
                self._watch_screen(screen)
            app.screenAdded.connect(self._on_screens_changed)
            app.screenRemoved.connect(self._on_screens_changed)

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def dim_level(self) -> int:
        return self._dim_level

    @property
    def last_error_code(self) -> str:
        return self._last_error_code

    @property
    def last_error_message(self) -> str:
        return self._last_error_message

    def enable(self, level: int = 100) -> bool:
        """Create overlays for all screens and show them."""
        if self._enabled:
            return self.set_brightness(level)
        self._dim_level = level
        if not self._create_overlays():
            self._enabled = False
            self._report_failure(
                "dimmer_overlay_failed",
                "无法为当前屏幕创建调暗层。",
            )
            return False
        try:
            for overlay in self._overlays:
                overlay.set_dim_level(level)
                overlay.show()
                if not overlay.isVisible():
                    raise RuntimeError("overlay did not become visible")
        except Exception:
            log.exception("Failed to show all dimmer overlays")
            self.disable()
            self._report_failure(
                "dimmer_overlay_failed",
                "调暗层未能在所有屏幕上显示。",
            )
            return False
        self._enabled = True
        self._last_error_code = ""
        self._last_error_message = ""
        log.info("Screen dimmer enabled at level %d", level)
        return True

    def disable(self) -> bool:
        """Hide and remove all overlays."""
        success = True
        for overlay in self._overlays:
            try:
                overlay.hide()
                overlay.close()
                overlay.deleteLater()
            except Exception:
                success = False
                log.exception("Failed to remove a dimmer overlay")
        self._overlays.clear()
        self._enabled = False
        self._dim_level = 0
        if success:
            self._last_error_code = ""
            self._last_error_message = ""
        else:
            self._report_failure(
                "dimmer_restore_failed",
                "部分调暗层未能正常移除。",
            )
        log.info("Screen dimmer disabled")
        return success

    def set_brightness(self, level: int) -> bool:
        """Update dim level on all overlays."""
        self._dim_level = max(0, min(200, level))
        if self._enabled and not self._overlays:
            self._report_failure(
                "dimmer_overlay_missing",
                "调暗层已丢失，请重新启用。",
            )
            self._enabled = False
            return False
        for overlay in self._overlays:
            overlay.set_dim_level(self._dim_level)
        return True

    def refresh_screens(self) -> bool:
        """Recreate overlays when screen configuration changes."""
        was_enabled = self._enabled
        saved_level = self._dim_level
        if not was_enabled:
            return True
        if not self.disable():
            return False
        return self.enable(saved_level)

    def _on_screens_changed(self, *_):
        """Keep overlay topology aligned with monitor hot-plug events."""
        app = QApplication.instance()
        if app is not None:
            for screen in app.screens():
                self._watch_screen(screen)
        if self._enabled:
            self.refresh_screens()

    def _report_failure(self, code: str, message: str) -> None:
        self._last_error_code = code
        self._last_error_message = message
        self.operation_failed.emit(code, message)

    def _watch_screen(self, screen: QScreen):
        identity = id(screen)
        if identity in self._watched_screens:
            return
        self._watched_screens.add(identity)
        screen.geometryChanged.connect(self._on_screens_changed)
        screen.availableGeometryChanged.connect(self._on_screens_changed)

    def _create_overlays(self) -> bool:
        """Create one overlay per screen."""
        app = QApplication.instance()
        if app is None:
            log.warning("No QApplication instance; cannot create overlays")
            return False
        screens = app.screens()
        if not screens:
            log.warning("No screens are available; cannot create overlays")
            return False
        try:
            for screen in screens:
                overlay = DimOverlay(screen)
                self._overlays.append(overlay)
        except Exception:
            log.exception("Failed to create dimmer overlays")
            for overlay in self._overlays:
                overlay.close()
                overlay.deleteLater()
            self._overlays.clear()
            return False
        return len(self._overlays) == len(screens)
