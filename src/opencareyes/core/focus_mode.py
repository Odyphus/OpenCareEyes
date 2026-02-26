"""Focus mode: dims everything except the active window."""

import logging

from PySide6.QtCore import QObject, QRect, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QApplication, QWidget

from opencareyes.platform.win32_api import (
    EVENT_SYSTEM_FOREGROUND,
    GWL_EXSTYLE,
    HWND_TOPMOST,
    HWND_NOTOPMOST,
    GW_HWNDPREV,
    SWP_NOMOVE,
    SWP_NOSIZE,
    SWP_NOACTIVATE,
    WS_EX_LAYERED,
    WS_EX_TRANSPARENT,
    WS_EX_TOOLWINDOW,
    WINEVENT_OUTOFCONTEXT,
    WINEVENTPROC,
    GetForegroundWindow,
    GetWindow,
    GetWindowLongW,
    IsWindow,
    SetWinEventHook,
    SetWindowLongW,
    SetWindowPos,
    UnhookWinEvent,
)

log = logging.getLogger(__name__)


class _FocusOverlay(QWidget):
    """Semi-transparent overlay placed behind the active window."""

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
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

    def set_dim_level(self, level: int):
        self._opacity = max(0, min(255, level))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, self._opacity))
        painter.end()


class FocusMode(QObject):
    """Dims background windows to help focus on the active window."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._enabled = False
        self._dim_level = 150
        self._overlay: _FocusOverlay | None = None
        self._hook = None
        self._callback = WINEVENTPROC(self._win_event_callback)

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def dim_level(self) -> int:
        return self._dim_level

    def enable(self):
        """Activate focus mode: hook foreground changes and create overlay."""
        if self._enabled:
            return
        self._overlay = _FocusOverlay()
        self._overlay.set_dim_level(self._dim_level)
        self._cover_all_screens()
        self._overlay.show()

        # Do NOT use WINEVENT_SKIPOWNPROCESS — we need to handle ALL
        # foreground changes, including our own settings panel.
        self._hook = SetWinEventHook(
            EVENT_SYSTEM_FOREGROUND,
            EVENT_SYSTEM_FOREGROUND,
            None,
            self._callback,
            0,
            0,
            WINEVENT_OUTOFCONTEXT,
        )
        if not self._hook:
            log.error("Failed to set WinEvent hook for focus mode")
            self._overlay.close()
            self._overlay = None
            return

        self._enabled = True
        self._on_foreground_changed(GetForegroundWindow())
        log.info("Focus mode enabled")

    def disable(self):
        """Deactivate focus mode: unhook and remove overlay."""
        if not self._enabled:
            return
        if self._hook:
            UnhookWinEvent(self._hook)
            self._hook = None
        if self._overlay:
            self._overlay.hide()
            self._overlay.close()
            self._overlay.deleteLater()
            self._overlay = None
        self._enabled = False
        log.info("Focus mode disabled")

    def set_dim_level(self, level: int):
        """Configure background dim level (0-255)."""
        self._dim_level = max(0, min(255, level))
        if self._overlay:
            self._overlay.set_dim_level(self._dim_level)

    def _on_foreground_changed(self, hwnd):
        """Place overlay just below the foreground window in Z-order."""
        if not self._enabled or not self._overlay or not hwnd:
            return

        overlay_hwnd = int(self._overlay.winId())
        if not overlay_hwnd:
            return

        # Skip if the foreground window IS our overlay
        if hwnd == overlay_hwnd:
            return

        # Strategy: insert the overlay directly behind the foreground window.
        # 1. Temporarily remove TOPMOST from overlay so we can position it
        #    relative to other windows without forcing anything topmost.
        # 2. Place overlay right behind the foreground window using
        #    hWndInsertAfter = hwnd (overlay goes just below hwnd).
        # 3. The foreground window stays in its normal Z-position — we never
        #    make it TOPMOST, so clicking other windows works normally.

        try:
            SetWindowPos(
                overlay_hwnd,
                hwnd,  # insert just below the foreground window
                0, 0, 0, 0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
            )
        except Exception:
            log.debug("SetWindowPos failed for overlay", exc_info=True)

    def _win_event_callback(self, hWinEventHook, event, hwnd, idObject,
                            idChild, dwEventThread, dwmsEventTime):
        """Raw WinEvent callback — dispatches to _on_foreground_changed."""
        if event == EVENT_SYSTEM_FOREGROUND and hwnd:
            self._on_foreground_changed(hwnd)

    def _cover_all_screens(self):
        """Size the overlay to cover the virtual desktop (all screens)."""
        app = QApplication.instance()
        if app is None:
            return
        screens = app.screens()
        if not screens:
            return
        bounding = QRect()
        for screen in screens:
            bounding = bounding.united(screen.geometry())
        self._overlay.setGeometry(bounding)
