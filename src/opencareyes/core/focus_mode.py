"""Focus mode: dims everything except the active window."""

import logging

from PySide6.QtCore import QObject, Qt, Signal, Slot
from PySide6.QtGui import QColor, QPainter, QScreen
from PySide6.QtWidgets import QApplication, QWidget

from opencareyes.platform.win32_api import (
    GWL_EXSTYLE,
    HWND_NOTOPMOST,
    SWP_NOMOVE,
    SWP_NOSIZE,
    SWP_NOACTIVATE,
    WS_EX_LAYERED,
    WS_EX_TRANSPARENT,
    WS_EX_TOOLWINDOW,
    GetForegroundWindow,
    GetWindowLongW,
    SetWindowLongW,
    SetWindowPos,
)
from opencareyes.platform.windows_event_hub import WindowsEventHub

log = logging.getLogger(__name__)


class _FocusOverlay(QWidget):
    """Semi-transparent overlay placed behind the active window."""

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self._opacity = 150

    def showEvent(self, event):
        """After the window is shown, apply Win32 click-through."""
        super().showEvent(event)
        hwnd = int(self.winId())
        if hwnd:
            ex = GetWindowLongW(hwnd, GWL_EXSTYLE)
            SetWindowLongW(
                hwnd, GWL_EXSTYLE,
                ex | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW,
            )
            # A focus overlay must participate in the normal Z-order. Leaving
            # it TOPMOST can cover task switching, UAC prompts and full-screen
            # windows on some Windows builds.
            SetWindowPos(
                hwnd,
                HWND_NOTOPMOST,
                0, 0, 0, 0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
            )

    def set_dim_level(self, level: int):
        self._opacity = max(0, min(255, level))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, self._opacity))
        painter.end()


class FocusMode(QObject):
    """Dims background windows to help focus on the active window."""

    operation_failed = Signal(str, str)

    def __init__(self, parent=None, *, watch_screen_events: bool = True):
        super().__init__(parent)
        self._enabled = False
        self._dim_level = 150
        self._overlays: list[_FocusOverlay] = []
        self._watched_screens: set[int] = set()
        self._last_error_code = ""
        self._last_error_message = ""
        self._event_hub = WindowsEventHub.shared()
        self._event_hub.install()
        self._event_hub.foreground_changed.connect(
            self._on_foreground_changed,
            Qt.QueuedConnection,
        )
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

    def enable(self) -> bool:
        """Activate focus mode: hook foreground changes and create overlay."""
        if self._enabled:
            return True
        if not self._create_overlays():
            self._report_failure(
                "focus_overlay_failed",
                "无法为当前屏幕创建专注遮罩。",
            )
            return False
        try:
            for overlay in self._overlays:
                overlay.show()
                if not overlay.isVisible():
                    raise RuntimeError("focus overlay did not become visible")
        except Exception:
            log.exception("Failed to show all focus overlays")
            self._destroy_overlays()
            self._report_failure(
                "focus_overlay_failed",
                "专注遮罩未能在所有屏幕上显示。",
            )
            return False

        self._enabled = True
        self._last_error_code = ""
        self._last_error_message = ""
        self._on_foreground_changed(GetForegroundWindow())
        log.info("Focus mode enabled")
        return True

    def disable(self) -> bool:
        """Deactivate focus mode: unhook and remove overlay."""
        if not self._enabled:
            return True
        removed = self._destroy_overlays()
        self._enabled = False
        if not removed:
            self._report_failure(
                "focus_restore_failed",
                "部分专注遮罩未能正常移除。",
            )
            return False
        self._last_error_code = ""
        self._last_error_message = ""
        log.info("Focus mode disabled")
        return True

    def set_dim_level(self, level: int):
        """Configure background dim level (0-255)."""
        self._dim_level = max(0, min(255, level))
        for overlay in self._overlays:
            overlay.set_dim_level(self._dim_level)

    def refresh_screens(self) -> bool:
        """Rebuild focus overlays after a native display change."""

        if not self._enabled:
            return True
        saved_level = self._dim_level
        if not self.disable():
            return False
        self._dim_level = saved_level
        return self.enable()

    @Slot(object)
    def _on_foreground_changed(self, hwnd):
        """Place overlay just below the foreground window in Z-order."""
        if not self._enabled or not self._overlays or not hwnd:
            return

        # Strategy: insert the overlay directly behind the foreground window.
        # 1. Temporarily remove TOPMOST from overlay so we can position it
        #    relative to other windows without forcing anything topmost.
        # 2. Place overlay right behind the foreground window using
        #    hWndInsertAfter = hwnd (overlay goes just below hwnd).
        # 3. The foreground window stays in its normal Z-position — we never
        #    make it TOPMOST, so clicking other windows works normally.

        for overlay in self._overlays:
            overlay_hwnd = int(overlay.winId())
            if not overlay_hwnd or hwnd == overlay_hwnd:
                continue
            try:
                SetWindowPos(
                    overlay_hwnd,
                    hwnd,
                    0, 0, 0, 0,
                    SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
                )
            except Exception:
                log.debug("SetWindowPos failed for focus overlay", exc_info=True)

    def _create_overlays(self) -> bool:
        """Create one lightweight overlay per physical screen."""
        app = QApplication.instance()
        if app is None:
            return False
        screens = app.screens()
        if not screens:
            return False
        try:
            for screen in screens:
                overlay = _FocusOverlay()
                overlay.setGeometry(screen.geometry())
                overlay.set_dim_level(self._dim_level)
                self._overlays.append(overlay)
        except Exception:
            log.exception("Failed to create focus overlays")
            self._destroy_overlays()
            return False
        return len(self._overlays) == len(screens)

    def _destroy_overlays(self) -> bool:
        success = True
        for overlay in self._overlays:
            try:
                overlay.hide()
                overlay.close()
                overlay.deleteLater()
            except Exception:
                success = False
                log.exception("Failed to remove a focus overlay")
        self._overlays.clear()
        return success

    def _on_screens_changed(self, *_):
        app = QApplication.instance()
        if app is not None:
            for screen in app.screens():
                self._watch_screen(screen)
        if not self._enabled:
            return
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
