"""RegisterHotKey-based global shortcuts with atomic replacement."""

from __future__ import annotations

import logging
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

from PySide6.QtCore import QObject, Qt, Signal, Slot

from opencareyes.platform.windows_event_hub import WindowsEventHub

if sys.platform == "win32":
    from opencareyes.platform import win32_api as api
else:  # pragma: no cover - Windows is the production target.
    api = None

log = logging.getLogger(__name__)

_MODIFIER_ALIASES = {
    "control": "ctrl",
    "option": "alt",
    "meta": "win",
    "super": "win",
    "windows": "win",
}
_MODIFIER_ORDER = ("ctrl", "alt", "shift", "win")
_SPECIAL_KEYS = {
    "backspace": 0x08,
    "tab": 0x09,
    "enter": 0x0D,
    "return": 0x0D,
    "esc": 0x1B,
    "escape": 0x1B,
    "space": 0x20,
    "pageup": 0x21,
    "pagedown": 0x22,
    "end": 0x23,
    "home": 0x24,
    "left": 0x25,
    "up": 0x26,
    "right": 0x27,
    "down": 0x28,
    "insert": 0x2D,
    "delete": 0x2E,
}


class HotkeyBackend(Protocol):
    available: bool

    def register(self, identifier: int, modifiers: int, virtual_key: int) -> bool: ...

    def unregister(self, identifier: int) -> bool: ...


class Win32HotkeyBackend:
    available = api is not None

    def register(self, identifier: int, modifiers: int, virtual_key: int) -> bool:
        if api is None:
            return False
        return bool(
            api.RegisterHotKey(
                None,
                int(identifier),
                int(modifiers) | api.MOD_NOREPEAT,
                int(virtual_key),
            )
        )

    def unregister(self, identifier: int) -> bool:
        if api is None:
            return False
        return bool(api.UnregisterHotKey(None, int(identifier)))


@dataclass(slots=True)
class _Registration:
    callback: Callable
    identifier: int


def parse_hotkey(sequence: str) -> tuple[str, int, int]:
    """Return canonical text, native modifiers and a virtual-key code."""

    tokens = [token.strip().casefold() for token in sequence.split("+")]
    if not tokens or any(not token for token in tokens):
        raise ValueError("快捷键不能为空")
    tokens = [_MODIFIER_ALIASES.get(token, token) for token in tokens]
    modifiers = {token for token in tokens if token in _MODIFIER_ORDER}
    keys = [token for token in tokens if token not in _MODIFIER_ORDER]
    if len(keys) != 1 or not modifiers:
        raise ValueError("快捷键必须包含修饰键和一个按键")
    if len(tokens) != len(modifiers) + 1:
        raise ValueError("快捷键包含重复按键")

    key = keys[0]
    if len(key) == 1 and ("a" <= key <= "z" or "0" <= key <= "9"):
        virtual_key = ord(key.upper())
    elif key.startswith("f") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        virtual_key = 0x70 + int(key[1:]) - 1
    else:
        virtual_key = _SPECIAL_KEYS.get(key, 0)
    if not virtual_key:
        raise ValueError(f"不支持的快捷键按键：{key}")

    if api is None:
        modifier_bits = {
            "alt": 0x0001,
            "ctrl": 0x0002,
            "shift": 0x0004,
            "win": 0x0008,
        }
    else:
        modifier_bits = {
            "alt": api.MOD_ALT,
            "ctrl": api.MOD_CONTROL,
            "shift": api.MOD_SHIFT,
            "win": api.MOD_WIN,
        }
    native_modifiers = 0
    for modifier in modifiers:
        native_modifiers |= modifier_bits[modifier]
    canonical = "+".join(
        [modifier for modifier in _MODIFIER_ORDER if modifier in modifiers] + [key]
    )
    return canonical, native_modifiers, virtual_key


class HotkeyManager(QObject):
    """Register shortcuts without a privileged keyboard hook."""

    activated = Signal(str)
    registration_failed = Signal(str, str)
    callback_failed = Signal(str, str)

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        backend: HotkeyBackend | None = None,
        event_hub: WindowsEventHub | None = None,
    ):
        super().__init__(parent)
        self._backend = backend or Win32HotkeyBackend()
        self._event_hub = event_hub or WindowsEventHub.shared()
        self._event_hub.install()
        self._registered: dict[str, _Registration] = {}
        self._by_id: dict[int, str] = {}
        self._next_identifier = 0x4F00
        self._event_hub.hotkey_activated.connect(
            self._on_native_hotkey,
            Qt.QueuedConnection,
        )
        self.activated.connect(self._dispatch, Qt.QueuedConnection)

    @property
    def available(self) -> bool:
        return bool(getattr(self._backend, "available", False))

    @property
    def registered_hotkeys(self) -> tuple[str, ...]:
        return tuple(self._registered)

    def register(self, hotkey: str, callback: Callable) -> bool:
        """Compatibility API; replacing one key remains transactional."""

        try:
            canonical, _modifiers, _key = parse_hotkey(hotkey)
        except ValueError as exc:
            self.registration_failed.emit(hotkey.strip().casefold(), str(exc))
            return False
        desired = {
            sequence: registration.callback
            for sequence, registration in self._registered.items()
            if sequence != canonical
        }
        desired[canonical] = callback
        return self.replace_all(desired)

    def unregister(self, hotkey: str) -> None:
        try:
            canonical, _modifiers, _key = parse_hotkey(hotkey)
        except ValueError:
            return
        registration = self._registered.get(canonical)
        if registration is None:
            return
        if self._backend.unregister(registration.identifier):
            self._registered.pop(canonical, None)
            self._by_id.pop(registration.identifier, None)
        else:
            log.warning("Failed to unregister hotkey: %s", canonical)

    def unregister_all(self) -> None:
        for sequence in tuple(self._registered):
            self.unregister(sequence)

    def set_hotkeys(self, mapping: Mapping[str, Callable]) -> bool:
        """Public atomic batch API used by controller settings."""

        return self.replace_all(mapping)

    def replace_all(self, mapping: Mapping[str, Callable]) -> bool:
        """Install the complete mapping or restore the previous mapping."""

        if not self.available:
            self.registration_failed.emit("", "系统全局快捷键不可用")
            return False
        parsed: list[tuple[str, int, int, Callable]] = []
        seen: set[str] = set()
        try:
            for raw_sequence, callback in mapping.items():
                if not callable(callback):
                    raise ValueError("快捷键回调不可调用")
                canonical, modifiers, key = parse_hotkey(raw_sequence)
                if canonical in seen:
                    raise ValueError(f"快捷键冲突：{canonical}")
                seen.add(canonical)
                parsed.append((canonical, modifiers, key, callback))
        except ValueError as exc:
            self.registration_failed.emit(str(raw_sequence), str(exc))
            return False

        previous = [
            (sequence, registration.callback)
            for sequence, registration in self._registered.items()
        ]
        if not self._unregister_everything():
            missing = [
                (*parse_hotkey(sequence), callback)
                for sequence, callback in previous
                if sequence not in self._registered
            ]
            restore_failed = self._install_parsed(missing)
            message = "无法释放现有快捷键"
            if restore_failed is not None:
                message += f"；旧快捷键恢复不完整：{restore_failed}"
            self.registration_failed.emit("", message)
            return False
        failed_sequence = self._install_parsed(parsed)
        if failed_sequence is None:
            return True

        self._unregister_everything()
        previous_parsed = [
            (*parse_hotkey(sequence), callback)
            for sequence, callback in previous
        ]
        # parse_hotkey returns canonical, modifiers, key, matching _install_parsed.
        restore_failed = self._install_parsed(previous_parsed)
        message = f"快捷键被其他程序占用：{failed_sequence}"
        if restore_failed is not None:
            message += f"；旧快捷键恢复不完整：{restore_failed}"
        self.registration_failed.emit(failed_sequence, message)
        return False

    def _install_parsed(
        self,
        parsed: list[tuple[str, int, int, Callable]],
    ) -> str | None:
        for sequence, modifiers, key, callback in parsed:
            identifier = self._allocate_identifier()
            try:
                registered = self._backend.register(identifier, modifiers, key)
            except Exception:
                registered = False
            if not registered:
                return sequence
            self._registered[sequence] = _Registration(callback, identifier)
            self._by_id[identifier] = sequence
            log.info("Registered hotkey: %s", sequence)
        return None

    def _unregister_everything(self) -> bool:
        success = True
        for sequence, registration in tuple(self._registered.items()):
            try:
                removed = self._backend.unregister(registration.identifier)
            except Exception:
                removed = False
            if removed:
                self._registered.pop(sequence, None)
                self._by_id.pop(registration.identifier, None)
            else:
                success = False
        return success

    def _allocate_identifier(self) -> int:
        identifier = self._next_identifier
        self._next_identifier += 1
        if self._next_identifier > 0xBFFF:
            self._next_identifier = 0x4F00
        return identifier

    @Slot(int)
    def _on_native_hotkey(self, identifier: int) -> None:
        sequence = self._by_id.get(int(identifier))
        if sequence is not None:
            self.activated.emit(sequence)

    @Slot(str)
    def _dispatch(self, hotkey: str) -> None:
        registration = self._registered.get(hotkey)
        if registration is None:
            return
        try:
            registration.callback()
        except Exception:
            log.exception("Hotkey callback failed: %s", hotkey)
            self.callback_failed.emit(
                hotkey,
                "快捷键操作未能完成，请在主界面重试。",
            )
