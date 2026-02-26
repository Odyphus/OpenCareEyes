"""QApplication subclass with single-instance control."""

import sys
import os
import logging

from PySide6.QtWidgets import QApplication
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtCore import Qt

from opencareyes.constants import APP_NAME, STYLES_DIR

log = logging.getLogger(__name__)


class OpenCareEyesApp(QApplication):
    """Single-instance application."""

    _instance = None

    def __init__(self, argv: list[str]):
        super().__init__(argv)
        OpenCareEyesApp._instance = self
        self.setApplicationName(APP_NAME)
        self.setQuitOnLastWindowClosed(False)

        self._server: QLocalServer | None = None
        self._load_stylesheet()

    @classmethod
    def instance(cls) -> "OpenCareEyesApp":
        return cls._instance

    # ---- Single instance ----

    def ensure_single_instance(self) -> bool:
        """Return True if this is the first instance, False otherwise."""
        socket = QLocalSocket()
        socket.connectToServer(APP_NAME)
        if socket.waitForConnected(500):
            socket.close()
            return False

        self._server = QLocalServer()
        self._server.removeServer(APP_NAME)
        if not self._server.listen(APP_NAME):
            log.warning("Could not start local server: %s", self._server.errorString())
        self._server.newConnection.connect(self._on_new_connection)
        return True

    def _on_new_connection(self):
        conn = self._server.nextPendingConnection()
        if conn:
            conn.close()
        log.info("Another instance tried to start; ignoring.")

    # ---- Stylesheet ----

    def _load_stylesheet(self):
        qss_path = os.path.join(STYLES_DIR, "dark.qss")
        if os.path.isfile(qss_path):
            with open(qss_path, "r", encoding="utf-8") as f:
                self.setStyleSheet(f.read())

    def cleanup(self):
        if self._server:
            self._server.close()
