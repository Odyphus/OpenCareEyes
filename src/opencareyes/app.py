"""Application bootstrap, dynamic theme handling and single-instance IPC."""

import os
import logging

from PySide6.QtGui import QFont, QFontDatabase, QIcon
from PySide6.QtWidgets import QApplication
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtCore import QTimer, Signal

from opencareyes.constants import APP_NAME, ICONS_DIR, STYLES_DIR

log = logging.getLogger(__name__)


class OpenCareEyesApp(QApplication):
    """Single-instance application."""

    activation_requested = Signal()

    _instance = None

    def __init__(self, argv: list[str]):
        super().__init__(argv)
        OpenCareEyesApp._instance = self
        self.setApplicationName(APP_NAME)
        self._load_windows_fonts()
        icon_path = os.path.join(ICONS_DIR, "opencareyes.ico")
        if os.path.isfile(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        self.setQuitOnLastWindowClosed(False)

        self._server: QLocalServer | None = None
        self._server_name = os.environ.get("OPENCAREYES_INSTANCE_KEY", APP_NAME)
        self._theme = "system"
        self._resolved_theme = "dark"
        self._theme_timer = QTimer(self)
        self._theme_timer.setInterval(3000)
        self._theme_timer.timeout.connect(self._poll_system_theme)
        self.apply_theme("system")
        self._theme_timer.start()

    def _load_windows_fonts(self) -> None:
        """Register reliable Latin/CJK fallbacks with Qt's font engine.

        Some portable Qt runtimes can enumerate Windows fonts but fail to
        obtain their outlines until the files are explicitly registered.
        """
        fonts_dir = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
        for filename in ("segoeui.ttf", "msyh.ttc"):
            path = os.path.join(fonts_dir, filename)
            if os.path.isfile(path):
                QFontDatabase.addApplicationFont(path)
        self.setFont(QFont("Microsoft YaHei UI", 10))

    @classmethod
    def instance(cls) -> "OpenCareEyesApp":
        return cls._instance

    # ---- Single instance ----

    def ensure_single_instance(self) -> bool:
        """Return True if this is the first instance, False otherwise."""
        socket = QLocalSocket()
        socket.connectToServer(self._server_name)
        if socket.waitForConnected(500):
            socket.write(b"activate")
            socket.flush()
            socket.waitForBytesWritten(500)
            socket.close()
            return False

        self._server = QLocalServer()
        self._server.removeServer(self._server_name)
        if not self._server.listen(self._server_name):
            log.warning("Could not start local server: %s", self._server.errorString())
        self._server.newConnection.connect(self._on_new_connection)
        return True

    def _on_new_connection(self):
        conn = self._server.nextPendingConnection()
        if conn:
            conn.waitForReadyRead(100)
            conn.readAll()
            conn.close()
        log.info("Another instance requested activation")
        self.activation_requested.emit()

    # ---- Stylesheet ----

    @property
    def theme(self) -> str:
        return self._theme

    def apply_theme(self, theme: str) -> str:
        """Apply ``light``, ``dark`` or the currently detected system theme.

        Returns the resolved theme so views can update theme-specific assets.
        """
        requested = theme if theme in {"light", "dark", "system"} else "system"
        resolved = self._resolve_theme(requested)
        if requested == self._theme and resolved == self._resolved_theme and self.styleSheet():
            return resolved

        qss_path = os.path.join(STYLES_DIR, f"{resolved}.qss")
        if os.path.isfile(qss_path):
            with open(qss_path, "r", encoding="utf-8") as f:
                self.setStyleSheet(f.read())
        else:
            log.warning("Theme stylesheet not found: %s", qss_path)
            self.setStyleSheet("")
        self._theme = requested
        self._resolved_theme = resolved
        self.setProperty("resolvedTheme", resolved)
        return resolved

    @staticmethod
    def _resolve_theme(theme: str) -> str:
        if theme != "system":
            return theme
        try:
            import darkdetect

            return "dark" if darkdetect.isDark() else "light"
        except Exception:
            return "dark"

    def _poll_system_theme(self):
        if self._theme != "system":
            return
        resolved = self._resolve_theme("system")
        if resolved != self._resolved_theme:
            self.apply_theme("system")

    def cleanup(self):
        self._theme_timer.stop()
        if self._server:
            self._server.close()
            self._server.removeServer(self._server_name)
