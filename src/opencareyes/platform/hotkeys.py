"""Global hotkeys with callbacks marshalled onto the Qt main thread."""

from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtCore import QObject, Qt, Signal, Slot

log = logging.getLogger(__name__)

try:
    import keyboard

    _HAS_KEYBOARD = True
except ImportError:
    keyboard = None
    _HAS_KEYBOARD = False
    log.warning("keyboard library not available; global hotkeys disabled")
except Exception:
    keyboard = None
    _HAS_KEYBOARD = False
    log.warning(
        "keyboard library failed to initialise (admin required?); "
        "global hotkeys disabled"
    )


class HotkeyManager(QObject):
    """Register global shortcuts without calling UI code from hook threads."""

    activated = Signal(str)
    registration_failed = Signal(str, str)
    callback_failed = Signal(str, str)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._registered: dict[str, tuple[Callable, object]] = {}
        self.activated.connect(self._dispatch, Qt.QueuedConnection)

    @property
    def available(self) -> bool:
        return _HAS_KEYBOARD

    @property
    def registered_hotkeys(self) -> tuple[str, ...]:
        return tuple(self._registered)

    def register(self, hotkey: str, callback: Callable) -> bool:
        """Register a shortcut, returning ``False`` on conflicts/errors."""
        hotkey = hotkey.strip().lower()
        if not hotkey:
            self.registration_failed.emit(hotkey, "Hotkey cannot be empty")
            return False
        if not callable(callback):
            self.registration_failed.emit(hotkey, "Callback is not callable")
            return False
        if not _HAS_KEYBOARD:
            self.registration_failed.emit(hotkey, "Global hotkeys are unavailable")
            return False
        if hotkey in self._registered:
            self.unregister(hotkey)

        try:
            # ``keyboard`` invokes this wrapper on its hook thread.  Emitting a
            # queued Qt signal is the only operation performed there.
            handle = keyboard.add_hotkey(
                hotkey,
                lambda sequence=hotkey: self.activated.emit(sequence),
                suppress=False,
            )
        except Exception as exc:
            log.exception("Failed to register hotkey: %s", hotkey)
            self.registration_failed.emit(hotkey, str(exc))
            return False

        self._registered[hotkey] = (callback, handle)
        log.info("Registered hotkey: %s", hotkey)
        return True

    def unregister(self, hotkey: str) -> None:
        hotkey = hotkey.strip().lower()
        registration = self._registered.pop(hotkey, None)
        if registration is None or not _HAS_KEYBOARD:
            return
        _, handle = registration
        try:
            keyboard.remove_hotkey(handle if handle is not None else hotkey)
        except (KeyError, ValueError):
            pass
        except Exception:
            log.exception("Failed to unregister hotkey: %s", hotkey)

    def unregister_all(self) -> None:
        for hotkey in list(self._registered):
            self.unregister(hotkey)

    @Slot(str)
    def _dispatch(self, hotkey: str) -> None:
        registration = self._registered.get(hotkey)
        if registration is None:
            return
        callback, _ = registration
        try:
            callback()
        except Exception as exc:
            log.exception("Hotkey callback failed: %s", hotkey)
            self.callback_failed.emit(hotkey, str(exc))
