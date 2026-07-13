"""RegisterHotKey parsing and atomic replacement tests."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from opencareyes.platform.hotkeys import HotkeyManager, parse_hotkey


class Hub(QObject):
    hotkey_activated = Signal(int)

    def install(self):
        return True


class Backend:
    available = True

    def __init__(self):
        self.active = {}
        self.fail_key = None
        self.fail_unregister = set()

    def register(self, identifier, modifiers, virtual_key):
        if virtual_key == self.fail_key:
            return False
        self.active[identifier] = (modifiers, virtual_key)
        return True

    def unregister(self, identifier):
        if identifier in self.fail_unregister:
            return False
        return self.active.pop(identifier, None) is not None


def test_parse_hotkey_normalises_aliases_and_order():
    canonical, modifiers, key = parse_hotkey("ALT + Control + N")

    assert canonical == "ctrl+alt+n"
    assert modifiers
    assert key == ord("N")


def test_failed_batch_registration_restores_complete_old_mapping():
    backend = Backend()
    manager = HotkeyManager(backend=backend, event_hub=Hub())

    def old_callback():
        return None

    assert manager.replace_all({"ctrl+alt+n": old_callback})
    backend.fail_key = ord("X")

    assert not manager.replace_all({"ctrl+alt+x": lambda: None})

    assert manager.registered_hotkeys == ("ctrl+alt+n",)
    assert tuple(value[1] for value in backend.active.values()) == (ord("N"),)


def test_native_activation_dispatches_callback_on_qt_queue(qtbot):
    backend = Backend()
    hub = Hub()
    manager = HotkeyManager(backend=backend, event_hub=hub)
    calls = []
    assert manager.replace_all({"ctrl+alt+n": lambda: calls.append("called")})
    identifier = next(iter(backend.active))

    hub.hotkey_activated.emit(identifier)

    qtbot.waitUntil(lambda: calls == ["called"])


def test_callback_failure_exposes_only_a_localized_message():
    manager = HotkeyManager(backend=Backend(), event_hub=Hub())
    failures = []
    manager.callback_failed.connect(
        lambda hotkey, message: failures.append((hotkey, message))
    )

    def fail_in_english():
        raise RuntimeError("private backend detail")

    assert manager.replace_all({"ctrl+alt+n": fail_in_english})

    manager._dispatch("ctrl+alt+n")

    assert failures == [
        ("ctrl+alt+n", "快捷键操作未能完成，请在主界面重试。")
    ]
