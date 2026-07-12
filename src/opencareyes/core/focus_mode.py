"""Focus mode: dims everything except the active window."""

import logging

from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QColor, QPainter, QScreen
from PySide6.QtWidgets import QApplication, QWidget

from opencareyes.platform.win32_api import (
    EVENT_SYSTEM_FOREGROUND,
    GWL_EXSTYLE,
    HWND_NOTOPMOST,
    SWP_NOMOVE,
    SWP_NOSIZE,
    SWP_NOACTIVATE,
    WS_EX_LAYERED,
    WS_EX_TRANSPARENT,
    WS_EX_TOOLWINDOW,
    WINEVENT_OUTOFCONTEXT,
    WINEVENTPROC,
    GetForegroundWindow,
    GetWindowLongW,
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

    def __init__(self, parent=None):
        super().__init__(parent)
        self._enabled = False
        self._dim_level = 150
        self._overlays: list[_FocusOverlay] = []
        self._watched_screens: set[int] = set()
        self._hook = None
        self._callback = WINEVENTPROC(self._win_event_callback)
        app = QApplication.instance()
        if app is not None:
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

    def enable(self):
        """Activate focus mode: hook foreground changes and create overlay."""
        if self._enabled:
            return
        self._create_overlays()
        for overlay in self._overlays:
            overlay.show()

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
            self._destroy_overlays()
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
        self._destroy_overlays()
        self._enabled = False
        log.info("Focus mode disabled")

    def set_dim_level(self, level: int):
        """Configure background dim level (0-255)."""
        self._dim_level = max(0, min(255, level))
        for overlay in self._overlays:
            overlay.set_dim_level(self._dim_level)

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

    def _win_event_callback(self, hWinEventHook, event, hwnd, idObject,
                            idChild, dwEventThread, dwmsEventTime):
        """Raw WinEvent callback — dispatches to _on_foreground_changed."""
        if event == EVENT_SYSTEM_FOREGROUND and hwnd:
            self._on_foreground_changed(hwnd)

    def _create_overlays(self):
        """Create one lightweight overlay per physical screen."""
        app = QApplication.instance()
        if app is None:
            return
        for screen in app.screens():
            overlay = _FocusOverlay()
            overlay.setGeometry(screen.geometry())
            overlay.set_dim_level(self._dim_level)
            self._overlays.append(overlay)

    def _destroy_overlays(self):
        for overlay in self._overlays:
            overlay.hide()
            overlay.close()
            overlay.deleteLater()
        self._overlays.clear()

    def _on_screens_changed(self, *_):
        app = QApplication.instance()
        if app is not None:
            for screen in app.screens():
                self._watch_screen(screen)
        if not self._enabled:
            return
        self._destroy_overlays()
        self._create_overlays()
        for overlay in self._overlays:
            overlay.show()
        self._on_foreground_changed(GetForegroundWindow())

    def _watch_screen(self, screen: QScreen):
        identity = id(screen)
        if identity in self._watched_screens:
            return
        self._watched_screens.add(identity)
        screen.geometryChanged.connect(self._on_screens_changed)
