"""Privacy-safe Windows context sampling with Qt-thread delivery."""

from __future__ import annotations

import ctypes
import logging
import ntpath
import os
import sys
import time
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from typing import Protocol

from PySide6.QtCore import (
    QAbstractNativeEventFilter,
    QObject,
    QTimer,
    Qt,
    Signal,
    Slot,
)

from opencareyes.domain.context import ContextSnapshot, SessionState
from opencareyes.platform.windows_event_hub import WindowsEventHub

log = logging.getLogger(__name__)

if sys.platform == "win32":
    from opencareyes.platform import win32_api as api
else:  # pragma: no cover - Windows is the supported production platform.
    api = None


class ContextBackend(Protocol):
    """Small injectable seam used by the sensor and deterministic tests."""

    def sample(self, session: SessionState) -> ContextSnapshot: ...

    def start_foreground_hook(self, callback: Callable[[], None]) -> bool: ...

    def stop_foreground_hook(self) -> None: ...


class Win32ContextBackend:
    """Read the current context without returning titles or executable paths."""

    _EXCLUDED_WINDOW_CLASSES = {"progman", "workerw", "shell_traywnd"}
    _FRAME_TOLERANCE = 2

    def __init__(self) -> None:
        if api is None:
            raise RuntimeError("Windows context APIs are unavailable")
        self._own_process_id = os.getpid()
        self._hook = None
        self._hook_callback = None

    def sample(self, session: SessionState) -> ContextSnapshot:
        hwnd = api.GetForegroundWindow()
        process_id = self._window_process_id(hwnd)
        is_own_window = process_id == self._own_process_id
        excluded_window = is_own_window or self._window_class(hwnd) in (
            self._EXCLUDED_WINDOW_CLASSES
        )
        app_id = "" if excluded_window else self._application_id(process_id)
        fullscreen = False if excluded_window else self._is_fullscreen(hwnd)

        return ContextSnapshot(
            session=session,
            foreground_app_id=app_id,
            fullscreen=fullscreen,
            notification_mode=self._notification_mode(),
            idle_seconds=self._idle_seconds(),
            captured_at=datetime.now().astimezone(),
        )

    def start_foreground_hook(self, callback: Callable[[], None]) -> bool:
        if self._hook:
            return True

        def on_foreground_event(_hook, _event, _hwnd, _object, _child, _thread, _time):
            callback()

        hook_callback = api.WINEVENTPROC(on_foreground_event)
        hook = api.SetWinEventHook(
            api.EVENT_SYSTEM_FOREGROUND,
            api.EVENT_SYSTEM_FOREGROUND,
            None,
            hook_callback,
            0,
            0,
            api.WINEVENT_OUTOFCONTEXT | api.WINEVENT_SKIPOWNPROCESS,
        )
        if not hook:
            return False
        self._hook_callback = hook_callback
        self._hook = hook
        return True

    def stop_foreground_hook(self) -> None:
        if self._hook:
            api.UnhookWinEvent(self._hook)
        self._hook = None
        self._hook_callback = None

    @staticmethod
    def _window_process_id(hwnd) -> int:
        if not hwnd:
            return 0
        process_id = api.wintypes.DWORD()
        api.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        return int(process_id.value)

    @staticmethod
    def _window_class(hwnd) -> str:
        if not hwnd:
            return ""
        buffer = ctypes.create_unicode_buffer(256)
        length = api.GetClassNameW(hwnd, buffer, len(buffer))
        return buffer.value[:length].casefold() if length else ""

    @staticmethod
    def _application_id(process_id: int) -> str:
        if not process_id:
            return ""
        process = api.OpenProcess(api.PROCESS_QUERY_LIMITED_INFORMATION, False, process_id)
        if not process:
            return ""
        try:
            capacity = 32768
            buffer = ctypes.create_unicode_buffer(capacity)
            size = api.wintypes.DWORD(capacity)
            if not api.QueryFullProcessImageNameW(
                process,
                0,
                buffer,
                ctypes.byref(size),
            ):
                return ""
            return ntpath.basename(buffer.value[: size.value]).casefold()[:128]
        finally:
            api.CloseHandle(process)

    @classmethod
    def _is_fullscreen(cls, hwnd) -> bool:
        if not hwnd or not api.IsWindow(hwnd) or api.IsIconic(hwnd):
            return False
        frame = api.RECT()
        result = api.DwmGetWindowAttribute(
            hwnd,
            api.DWMWA_EXTENDED_FRAME_BOUNDS,
            ctypes.byref(frame),
            ctypes.sizeof(frame),
        )
        if result != 0:
            return False
        monitor = api.MonitorFromWindow(hwnd, api.MONITOR_DEFAULTTONEAREST)
        if not monitor:
            return False
        info = api.MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(info)
        if not api.GetMonitorInfoW(monitor, ctypes.byref(info)):
            return False
        bounds = info.rcMonitor
        tolerance = cls._FRAME_TOLERANCE
        return all(
            abs(actual - expected) <= tolerance
            for actual, expected in (
                (frame.left, bounds.left),
                (frame.top, bounds.top),
                (frame.right, bounds.right),
                (frame.bottom, bounds.bottom),
            )
        )

    @staticmethod
    def _notification_mode() -> str:
        state = ctypes.c_int()
        if api.SHQueryUserNotificationState(ctypes.byref(state)) != 0:
            return "unavailable"
        if state.value == api.QUNS_RUNNING_D3D_FULL_SCREEN:
            return "d3d_fullscreen"
        if state.value == api.QUNS_PRESENTATION_MODE:
            return "presentation"
        if state.value in {api.QUNS_NOT_PRESENT, api.QUNS_BUSY}:
            return "busy"
        return "normal"

    @staticmethod
    def _idle_seconds() -> int:
        info = api.LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(info)
        if not api.GetLastInputInfo(ctypes.byref(info)):
            raise OSError("GetLastInputInfo failed")
        elapsed_ms = (int(api.GetTickCount()) - int(info.dwTime)) & 0xFFFFFFFF
        return elapsed_ms // 1000


class _UnavailableBackend:
    def sample(self, session: SessionState) -> ContextSnapshot:
        raise RuntimeError("Windows context APIs are unavailable")

    def start_foreground_hook(self, callback: Callable[[], None]) -> bool:
        return False

    def stop_foreground_hook(self) -> None:
        return None


class ContextSensor(QObject):
    """Poll context once per second and marshal native events to the Qt thread."""

    snapshot_changed = Signal(object)
    availability_changed = Signal(bool, str)

    _sample_requested = Signal()
    _session_lock_requested = Signal(bool)
    _system_suspend_requested = Signal(bool)

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        backend: ContextBackend | None = None,
        poll_interval_ms: int = 1000,
        stale_after_seconds: float = 5.0,
        monotonic: Callable[[], float] = time.monotonic,
        event_hub: WindowsEventHub | None = None,
    ) -> None:
        super().__init__(parent)
        self._backend: ContextBackend = backend or self._default_backend()
        self._monotonic = monotonic
        self._stale_after_seconds = stale_after_seconds
        self._current_snapshot = ContextSnapshot()
        self._available = False
        self._availability_reason = "not_started"
        self._started = False
        self._session_locked = False
        self._system_suspended = False
        self._last_success_at: float | None = None
        self._failure_started_at: float | None = None
        self._event_hub = (
            event_hub
            if event_hub is not None
            else (WindowsEventHub.shared() if backend is None and api is not None else None)
        )

        self._timer = QTimer(self)
        self._timer.setInterval(max(100, int(poll_interval_ms)))
        self._timer.timeout.connect(self._sample_now)
        self._sample_requested.connect(self._sample_now, Qt.QueuedConnection)
        self._session_lock_requested.connect(
            self._apply_session_locked,
            Qt.QueuedConnection,
        )
        self._system_suspend_requested.connect(
            self._apply_system_suspended,
            Qt.QueuedConnection,
        )
        if self._event_hub is not None:
            self._event_hub.foreground_changed.connect(
                self._request_sample,
                Qt.QueuedConnection,
            )
            self._event_hub.display_changed.connect(
                self._request_sample,
                Qt.QueuedConnection,
            )
            self._event_hub.clock_changed.connect(
                self._request_sample,
                Qt.QueuedConnection,
            )
            self._event_hub.session_locked.connect(
                self.set_session_locked,
                Qt.QueuedConnection,
            )
            self._event_hub.system_suspended.connect(
                self.set_system_suspended,
                Qt.QueuedConnection,
            )

    @staticmethod
    def _default_backend() -> ContextBackend:
        if api is None:
            return _UnavailableBackend()
        return Win32ContextBackend()

    @property
    def current_snapshot(self) -> ContextSnapshot:
        return self._current_snapshot

    @property
    def available(self) -> bool:
        return self._available

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        if self._event_hub is not None:
            self._event_hub.install()
            hook_started = self._event_hub.foreground_hook_available
        else:
            try:
                hook_started = self._backend.start_foreground_hook(
                    self._sample_requested.emit
                )
            except Exception:
                hook_started = False
        if not hook_started:
            log.warning("Foreground event hook unavailable; using periodic sampling")
        self._timer.start()
        self._sample_now()

    def stop(self) -> None:
        if not self._started:
            return
        self._started = False
        self._timer.stop()
        if self._event_hub is None:
            try:
                self._backend.stop_foreground_hook()
            except Exception:
                log.warning("Foreground event hook could not be stopped cleanly")

    def set_session_locked(self, locked: bool) -> None:
        """Inject WTS lock/unlock state; handling is always queued to Qt."""
        self._session_lock_requested.emit(bool(locked))

    def set_system_suspended(self, suspended: bool) -> None:
        """Inject power suspend/resume state; handling is always queued to Qt."""
        self._system_suspend_requested.emit(bool(suspended))

    @Slot()
    @Slot(object)
    def _request_sample(self, *_args) -> None:
        self._sample_requested.emit()

    def _session(self) -> SessionState:
        if self._system_suspended:
            return "suspended"
        if self._session_locked:
            return "locked"
        return "active"

    @Slot(bool)
    def _apply_session_locked(self, locked: bool) -> None:
        self._session_locked = locked
        self._publish(replace(self._current_snapshot, session=self._session()))
        if self._started:
            self._sample_now()

    @Slot(bool)
    def _apply_system_suspended(self, suspended: bool) -> None:
        self._system_suspended = suspended
        self._publish(replace(self._current_snapshot, session=self._session()))
        if self._started:
            self._sample_now()

    @Slot()
    def _sample_now(self) -> None:
        if not self._started:
            return
        now = self._monotonic()
        try:
            snapshot = self._backend.sample(self._session())
        except Exception:
            self._handle_failure(now)
            return

        self._last_success_at = now
        self._failure_started_at = None
        self._set_availability(True, "")
        if snapshot.session != self._session():
            snapshot = replace(snapshot, session=self._session())
        self._publish(snapshot)

    def _handle_failure(self, now: float) -> None:
        if self._failure_started_at is None:
            self._failure_started_at = now
        has_fresh_snapshot = (
            self._last_success_at is not None
            and now - self._failure_started_at < self._stale_after_seconds
        )
        if has_fresh_snapshot:
            return

        self._set_availability(False, "context_probe_failed")
        unavailable = replace(
            self._current_snapshot,
            session=self._session(),
            foreground_app_id="",
            fullscreen=False,
            notification_mode="unavailable",
            idle_seconds=0,
            captured_at=datetime.now().astimezone(),
        )
        self._publish(unavailable)

    def _set_availability(self, available: bool, reason: str) -> None:
        if (available, reason) == (self._available, self._availability_reason):
            return
        self._available = available
        self._availability_reason = reason
        self.availability_changed.emit(available, reason)

    def _publish(self, snapshot: ContextSnapshot) -> None:
        if snapshot == self._current_snapshot:
            return
        self._current_snapshot = snapshot
        self.snapshot_changed.emit(snapshot)


class WindowsSessionEventFilter(QAbstractNativeEventFilter):
    """Bridge WTS and power messages into the sensor's queued setters.

    Install this object on ``QCoreApplication`` and call :meth:`register` with
    a real top-level window handle after that window has been created.
    """

    def __init__(self, sensor: ContextSensor) -> None:
        super().__init__()
        self._sensor = sensor
        self._hwnd = 0
        self._wts_registered = False

    def register(self, hwnd: int) -> bool:
        """Register a top-level HWND for WTS session notifications."""
        self.unregister()
        if api is None or not hwnd:
            return False
        self._hwnd = int(hwnd)
        try:
            self._wts_registered = bool(
                api.WTSRegisterSessionNotification(
                    api.wintypes.HWND(self._hwnd),
                    api.NOTIFY_FOR_THIS_SESSION,
                )
            )
        except Exception:
            self._wts_registered = False
        if not self._wts_registered:
            log.warning("WTS session notifications are unavailable")
        return self._wts_registered

    def unregister(self) -> None:
        if api is not None and self._hwnd and self._wts_registered:
            try:
                api.WTSUnRegisterSessionNotification(
                    api.wintypes.HWND(self._hwnd)
                )
            except Exception:
                log.warning("WTS session notifications could not be unregistered")
        self._hwnd = 0
        self._wts_registered = False

    @staticmethod
    def interpret_message(message: int, wparam: int) -> tuple[str, bool] | None:
        """Translate a native message into a sensor setter and value."""
        if api is None:
            return None
        if message == api.WM_WTSSESSION_CHANGE:
            if wparam == api.WTS_SESSION_LOCK:
                return "session_locked", True
            if wparam == api.WTS_SESSION_UNLOCK:
                return "session_locked", False
        elif message == api.WM_POWERBROADCAST:
            if wparam == api.PBT_APMSUSPEND:
                return "system_suspended", True
            if wparam in {
                api.PBT_APMRESUMECRITICAL,
                api.PBT_APMRESUMESUSPEND,
                api.PBT_APMRESUMEAUTOMATIC,
            }:
                return "system_suspended", False
        return None

    def nativeEventFilter(self, _event_type, message):  # noqa: N802
        if api is None or not self._hwnd:
            return False, 0
        try:
            address = int(message)
            if not address:
                return False, 0
            native_message = ctypes.cast(
                address,
                ctypes.POINTER(api.MSG),
            ).contents
            if int(native_message.hwnd or 0) != self._hwnd:
                return False, 0
            event = self.interpret_message(
                int(native_message.message),
                int(native_message.wParam),
            )
        except (TypeError, ValueError, OSError):
            return False, 0

        if event == ("session_locked", True):
            self._sensor.set_session_locked(True)
        elif event == ("session_locked", False):
            self._sensor.set_session_locked(False)
        elif event == ("system_suspended", True):
            self._sensor.set_system_suspended(True)
        elif event == ("system_suspended", False):
            self._sensor.set_system_suspended(False)
        return False, 0
