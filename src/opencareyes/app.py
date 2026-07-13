"""Application bootstrap, dynamic theme handling and single-instance IPC."""

import logging
import os

from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QApplication
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtCore import QTimer, Signal

from opencareyes.constants import APP_NAME, ICONS_DIR, STYLES_DIR

log = logging.getLogger(__name__)


def client_area_animations_enabled() -> bool:
    """Return the Windows client-area animation preference.

    Non-Windows development environments and unavailable native APIs default
    to animations enabled. A failure must never prevent application startup.
    """
    if os.name != "nt":
        return True
    try:
        import ctypes

        enabled = ctypes.c_int()
        success = ctypes.windll.user32.SystemParametersInfoW(
            0x1042,  # SPI_GETCLIENTAREAANIMATION
            0,
            ctypes.byref(enabled),
            0,
        )
        return bool(enabled.value) if success else True
    except Exception:
        log.debug("Could not read the Windows animation preference", exc_info=True)
        return True


def high_contrast_enabled() -> bool:
    """Return the Windows high-contrast preference without changing it."""

    if os.name != "nt":
        return False
    try:
        import ctypes
        import ctypes.wintypes as wintypes

        class HighContrast(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.UINT),
                ("dwFlags", wintypes.DWORD),
                ("lpszDefaultScheme", wintypes.LPWSTR),
            ]

        value = HighContrast()
        value.cbSize = ctypes.sizeof(value)
        success = ctypes.windll.user32.SystemParametersInfoW(
            0x0042,  # SPI_GETHIGHCONTRAST
            value.cbSize,
            ctypes.byref(value),
            0,
        )
        return bool(success and value.dwFlags & 0x00000001)
    except Exception:
        log.debug("Could not read the Windows high-contrast preference", exc_info=True)
        return False


class OpenCareEyesApp(QApplication):
    """Single-instance application."""

    activation_requested = Signal()
    theme_changed = Signal(str)
    motion_changed = Signal(bool)
    high_contrast_changed = Signal(bool)

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
        self._resolved_theme = ""
        self._motion_enabled = client_area_animations_enabled()
        self._high_contrast_enabled = high_contrast_enabled()
        self._applied_high_contrast = None
        self._preference_timer = QTimer(self)
        self._preference_timer.setInterval(3000)
        self._preference_timer.timeout.connect(self._poll_system_preferences)
        self.apply_theme("system")
        self._preference_timer.start()

    def _load_windows_fonts(self) -> None:
        """Set Windows UI font fallbacks without loading font files eagerly.

        Explicitly enumerating or registering the large CJK collection adds a
        substantial working-set cost to a tray-only session. Qt and DirectWrite
        resolve this ordered list when text is actually painted.
        """
        font = QFont()
        font.setFamilies(["Microsoft YaHei UI", "Segoe UI", "Arial"])
        font.setPointSize(10)
        self.setFont(font)

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

    @property
    def resolved_theme(self) -> str:
        return self._resolved_theme

    @property
    def motion_enabled(self) -> bool:
        """Whether decorative client-area animations should run."""
        return self._motion_enabled

    @property
    def high_contrast_enabled(self) -> bool:
        return self._high_contrast_enabled

    def apply_theme(self, theme: str) -> str:
        """Apply ``light``, ``dark`` or the currently detected system theme.

        Returns the resolved theme so views can update theme-specific assets.
        """
        requested = theme if theme in {"light", "dark", "system"} else "system"
        resolved = self._resolve_theme(requested)
        high_contrast = self._high_contrast_enabled
        if (
            requested == self._theme
            and resolved == self._resolved_theme
            and high_contrast == self._applied_high_contrast
        ):
            return resolved

        if high_contrast:
            # Fixed brand colours can make native high-contrast palettes
            # unreadable, so let Qt/Windows provide all control colours.
            self.setStyleSheet("")
        else:
            qss_path = os.path.join(STYLES_DIR, f"{resolved}.qss")
            if os.path.isfile(qss_path):
                with open(qss_path, "r", encoding="utf-8") as f:
                    self.setStyleSheet(f.read())
            else:
                log.warning(
                    "Theme stylesheet not found: %s (theme=%s)",
                    os.path.basename(qss_path),
                    resolved,
                )
                self.setStyleSheet("")
        self._theme = requested
        self._resolved_theme = resolved
        self._applied_high_contrast = high_contrast
        self.setProperty("resolvedTheme", resolved)
        self.setProperty("highContrast", high_contrast)
        self.theme_changed.emit(resolved)
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

    def _poll_system_preferences(self) -> None:
        high_contrast = high_contrast_enabled()
        # Keep the v0.3 duck-typed test/application adapters compatible: an
        # adapter without the new high-contrast fields simply starts tracking
        # on its next full application construction.
        if high_contrast != getattr(self, "_high_contrast_enabled", high_contrast):
            self._high_contrast_enabled = high_contrast
            self.apply_theme(self._theme)
            self.high_contrast_changed.emit(high_contrast)

        if self._theme == "system":
            resolved = self._resolve_theme("system")
            if resolved != self._resolved_theme:
                self.apply_theme("system")

        motion_enabled = client_area_animations_enabled()
        if motion_enabled != self._motion_enabled:
            self._motion_enabled = motion_enabled
            self.motion_changed.emit(motion_enabled)

    def _poll_system_theme(self) -> None:
        """Compatibility wrapper for callers from v0.2."""
        self._poll_system_preferences()

    def cleanup(self):
        self._preference_timer.stop()
        if self._server:
            self._server.close()
            self._server.removeServer(self._server_name)
