"""Global hotkey management using the keyboard library.

Falls back gracefully when running without admin privileges.
"""

import logging
from typing import Callable

log = logging.getLogger(__name__)

try:
    import keyboard
    _HAS_KEYBOARD = True
except ImportError:
    _HAS_KEYBOARD = False
    log.warning("keyboard library not available; global hotkeys disabled")
except Exception:
    _HAS_KEYBOARD = False
    log.warning("keyboard library failed to initialise (admin required?); global hotkeys disabled")


class HotkeyManager:
    """Register and unregister global hotkeys."""

    def __init__(self):
        self._registered: dict[str, Callable] = {}

    def register(self, hotkey: str, callback: Callable):
        if not _HAS_KEYBOARD:
            return
        if hotkey in self._registered:
            self.unregister(hotkey)
        try:
            keyboard.add_hotkey(hotkey, callback, suppress=False)
            self._registered[hotkey] = callback
            log.info("Registered hotkey: %s", hotkey)
        except Exception:
            log.exception("Failed to register hotkey: %s", hotkey)

    def unregister(self, hotkey: str):
        if not _HAS_KEYBOARD:
            return
        if hotkey in self._registered:
            try:
                keyboard.remove_hotkey(hotkey)
            except (KeyError, ValueError):
                pass
            del self._registered[hotkey]

    def unregister_all(self):
        for hk in list(self._registered):
            self.unregister(hk)
