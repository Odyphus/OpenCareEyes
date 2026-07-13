"""One Qt bridge for process-wide Windows notifications."""

from __future__ import annotations

import ctypes
import logging
import sys

from PySide6.QtCore import (
    QAbstractNativeEventFilter,
    QCoreApplication,
    QObject,
    QTimer,
    Qt,
    Signal,
    Slot,
)

if sys.platform == "win32":
    from opencareyes.platform import win32_api as api
else:  # pragma: no cover - Windows is the production target.
    api = None

log = logging.getLogger(__name__)
_TIMEZONE_UNAVAILABLE = object()


class WindowsEventHub(QObject, QAbstractNativeEventFilter):
    """Publish native callbacks as queued Qt signals on the main thread."""

    foreground_changed = Signal(object)
    session_locked = Signal(bool)
    system_suspended = Signal(bool)
    display_changed = Signal()
    clock_changed = Signal()
    hotkey_activated = Signal(int)

    _foreground_requested = Signal(object)
    _shared: "WindowsEventHub | None" = None

    def __init__(self, parent: QObject | None = None, *, native_api=None):
        QObject.__init__(self, parent)
        QAbstractNativeEventFilter.__init__(self)
        self._api = native_api if native_api is not None else api
        self._installed = False
        self._hwnd = 0
        self._wts_registered = False
        self._hook = None
        self._hook_callback = None
        self._screen_application = None
        self._watched_screens: dict[int, object] = {}
        self._display_timer = QTimer(self)
        self._display_timer.setSingleShot(True)
        self._display_timer.setInterval(100)
        self._display_timer.timeout.connect(self.display_changed)
        self._timezone_fingerprint = self._read_timezone_fingerprint()
        self._foreground_requested.connect(
            self._publish_foreground,
            Qt.QueuedConnection,
        )

    @classmethod
    def shared(cls) -> "WindowsEventHub":
        if cls._shared is None:
            cls._shared = cls()
        return cls._shared

    @property
    def installed(self) -> bool:
        return self._installed

    @property
    def foreground_hook_available(self) -> bool:
        return bool(self._hook)

    def install(self, application: QCoreApplication | None = None) -> bool:
        if self._installed:
            return True
        application = application or QCoreApplication.instance()
        if application is None:
            return False
        application.installNativeEventFilter(self)
        self._installed = True
        self._install_screen_events(application)
        self._start_foreground_hook()
        return True

    def register_window(self, hwnd: int) -> bool:
        """Register the main HWND for WTS lock and unlock notifications."""

        self.unregister_window()
        if self._api is None or not hwnd:
            return False
        self._hwnd = int(hwnd)
        try:
            self._wts_registered = bool(
                self._api.WTSRegisterSessionNotification(
                    self._api.wintypes.HWND(self._hwnd),
                    self._api.NOTIFY_FOR_THIS_SESSION,
                )
            )
        except Exception:
            self._wts_registered = False
        return self._wts_registered

    def unregister_window(self) -> None:
        if self._api is not None and self._hwnd and self._wts_registered:
            try:
                self._api.WTSUnRegisterSessionNotification(
                    self._api.wintypes.HWND(self._hwnd)
                )
            except Exception:
                log.warning("WTS notifications could not be unregistered")
        self._hwnd = 0
        self._wts_registered = False

    def shutdown(self, application: QCoreApplication | None = None) -> None:
        self.unregister_window()
        self._display_timer.stop()
        self._disconnect_screen_events()
        if self._api is not None and self._hook:
            try:
                self._api.UnhookWinEvent(self._hook)
            except Exception:
                log.warning("Foreground hook could not be removed")
        self._hook = None
        self._hook_callback = None
        application = application or QCoreApplication.instance()
        if self._installed and application is not None:
            application.removeNativeEventFilter(self)
        self._installed = False

    def interpret_message(
        self,
        message: int,
        wparam: int,
    ) -> tuple[str, object] | None:
        local_api = self._api
        if local_api is None:
            return None
        if message == local_api.WM_WTSSESSION_CHANGE:
            if wparam == local_api.WTS_SESSION_LOCK:
                return "session_locked", True
            if wparam == local_api.WTS_SESSION_UNLOCK:
                return "session_locked", False
        if message == local_api.WM_POWERBROADCAST:
            if wparam == local_api.PBT_APMSUSPEND:
                return "system_suspended", True
            if wparam in {
                local_api.PBT_APMRESUMECRITICAL,
                local_api.PBT_APMRESUMESUSPEND,
                local_api.PBT_APMRESUMEAUTOMATIC,
            }:
                return "system_suspended", False
        if message == local_api.WM_DISPLAYCHANGE:
            return "display_changed", None
        if message == local_api.WM_SETTINGCHANGE:
            if self._refresh_timezone_fingerprint():
                return "clock_changed", None
            return None
        if message == local_api.WM_TIMECHANGE:
            self._refresh_timezone_fingerprint(notify=False)
            return "clock_changed", None
        if message == local_api.WM_HOTKEY:
            return "hotkey_activated", int(wparam)
        return None

    def nativeEventFilter(self, _event_type, message):  # noqa: N802
        if self._api is None:
            return False, 0
        try:
            address = int(message)
            if not address:
                return False, 0
            native_message = ctypes.cast(
                address,
                ctypes.POINTER(self._api.MSG),
            ).contents
            message_id = int(native_message.message)
            hwnd = int(native_message.hwnd or 0)
            if (
                message_id != self._api.WM_HOTKEY
                and self._hwnd
                and hwnd not in {0, self._hwnd}
            ):
                return False, 0
            event = self.interpret_message(
                message_id,
                int(native_message.wParam),
            )
        except (TypeError, ValueError, OSError):
            return False, 0
        if event is None:
            return False, 0
        name, value = event
        if name == "session_locked":
            self.session_locked.emit(bool(value))
        elif name == "system_suspended":
            self.system_suspended.emit(bool(value))
        elif name == "display_changed":
            self._queue_display_changed()
        elif name == "clock_changed":
            self.clock_changed.emit()
        elif name == "hotkey_activated":
            self.hotkey_activated.emit(int(value))
        return False, 0

    def _read_timezone_fingerprint(self):
        reader = getattr(
            self._api,
            "get_dynamic_time_zone_fingerprint",
            None,
        )
        if reader is None:
            return _TIMEZONE_UNAVAILABLE
        try:
            return reader()
        except Exception:
            log.warning(
                "Windows time-zone configuration could not be queried",
                exc_info=True,
            )
            return _TIMEZONE_UNAVAILABLE

    def _refresh_timezone_fingerprint(self, *, notify: bool = True) -> bool:
        current = self._read_timezone_fingerprint()
        if current is _TIMEZONE_UNAVAILABLE:
            return False
        previous = self._timezone_fingerprint
        self._timezone_fingerprint = current
        return (
            notify
            and previous is not _TIMEZONE_UNAVAILABLE
            and current != previous
        )

    def _start_foreground_hook(self) -> bool:
        if self._api is None or self._hook:
            return bool(self._hook)

        def callback(_hook, _event, hwnd, _object, _child, _thread, _time):
            self._foreground_requested.emit(int(hwnd or 0))

        try:
            hook_callback = self._api.WINEVENTPROC(callback)
            hook = self._api.SetWinEventHook(
                self._api.EVENT_SYSTEM_FOREGROUND,
                self._api.EVENT_SYSTEM_FOREGROUND,
                None,
                hook_callback,
                0,
                0,
                self._api.WINEVENT_OUTOFCONTEXT,
            )
        except Exception:
            return False
        if not hook:
            return False
        self._hook_callback = hook_callback
        self._hook = hook
        return True

    @Slot(object)
    def _publish_foreground(self, hwnd) -> None:
        self.foreground_changed.emit(hwnd)

    @Slot()
    @Slot(object)
    def _queue_display_changed(self, *_args) -> None:
        """Coalesce native and Qt topology notifications into one event."""

        self._display_timer.start()

    @Slot(object)
    def _on_screen_added(self, screen) -> None:
        self._watch_screen(screen)
        self._queue_display_changed()

    @Slot(object)
    def _on_screen_removed(self, screen) -> None:
        self._unwatch_screen(screen)
        self._queue_display_changed()

    def _install_screen_events(self, application) -> None:
        screen_added = getattr(application, "screenAdded", None)
        screen_removed = getattr(application, "screenRemoved", None)
        screens = getattr(application, "screens", None)
        if screen_added is None or screen_removed is None or not callable(screens):
            return
        self._screen_application = application
        screen_added.connect(self._on_screen_added)
        screen_removed.connect(self._on_screen_removed)
        for screen in screens():
            self._watch_screen(screen)

    def _watch_screen(self, screen) -> None:
        identity = id(screen)
        if identity in self._watched_screens:
            return
        self._watched_screens[identity] = screen
        for name in (
            "geometryChanged",
            "availableGeometryChanged",
            "logicalDotsPerInchChanged",
            "physicalDotsPerInchChanged",
        ):
            signal = getattr(screen, name, None)
            if signal is not None:
                signal.connect(self._queue_display_changed)

    def _unwatch_screen(self, screen) -> None:
        watched = self._watched_screens.pop(id(screen), None)
        if watched is None:
            return
        for name in (
            "geometryChanged",
            "availableGeometryChanged",
            "logicalDotsPerInchChanged",
            "physicalDotsPerInchChanged",
        ):
            try:
                signal = getattr(watched, name, None)
                if signal is not None:
                    signal.disconnect(self._queue_display_changed)
            except (RuntimeError, TypeError):
                pass

    def _disconnect_screen_events(self) -> None:
        application = self._screen_application
        if application is not None:
            for name, slot in (
                ("screenAdded", self._on_screen_added),
                ("screenRemoved", self._on_screen_removed),
            ):
                signal = getattr(application, name, None)
                if signal is not None:
                    try:
                        signal.disconnect(slot)
                    except (RuntimeError, TypeError):
                        pass
        for screen in tuple(self._watched_screens.values()):
            self._unwatch_screen(screen)
        self._screen_application = None
