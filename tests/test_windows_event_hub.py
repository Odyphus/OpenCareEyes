"""Native event hub message translation tests."""

from types import SimpleNamespace

from PySide6.QtCore import QObject, Signal
from PySide6.QtTest import QSignalSpy

from opencareyes.platform.windows_event_hub import WindowsEventHub


def _api(timezone_fingerprint=None):
    if timezone_fingerprint is None:
        timezone_fingerprint = {"value": ("China Standard Time", -480, False)}
    return SimpleNamespace(
        WM_WTSSESSION_CHANGE=1,
        WTS_SESSION_LOCK=2,
        WTS_SESSION_UNLOCK=3,
        WM_POWERBROADCAST=4,
        PBT_APMSUSPEND=5,
        PBT_APMRESUMECRITICAL=6,
        PBT_APMRESUMESUSPEND=7,
        PBT_APMRESUMEAUTOMATIC=8,
        WM_DISPLAYCHANGE=9,
        WM_TIMECHANGE=10,
        WM_SETTINGCHANGE=11,
        WM_HOTKEY=12,
        get_dynamic_time_zone_fingerprint=lambda: timezone_fingerprint["value"],
    )


def test_interpret_message_uses_injected_native_api():
    hub = WindowsEventHub(native_api=_api())

    assert hub.interpret_message(9, 0) == ("display_changed", None)
    assert hub.interpret_message(10, 0) == ("clock_changed", None)
    assert hub.interpret_message(11, 0) is None
    assert hub.interpret_message(12, 42) == ("hotkey_activated", 42)
    assert hub.interpret_message(1, 2) == ("session_locked", True)
    assert hub.interpret_message(4, 8) == ("system_suspended", False)
    assert hub.interpret_message(999, 0) is None


def test_setting_change_only_reports_a_real_timezone_change():
    timezone_fingerprint = {
        "value": ("China Standard Time", -480, False),
    }
    hub = WindowsEventHub(native_api=_api(timezone_fingerprint))

    assert hub.interpret_message(11, 0) is None

    timezone_fingerprint["value"] = ("Tokyo Standard Time", -540, False)
    assert hub.interpret_message(11, 0) == ("clock_changed", None)
    assert hub.interpret_message(11, 0) is None


def test_time_change_keeps_working_and_refreshes_timezone_baseline():
    timezone_fingerprint = {
        "value": ("China Standard Time", -480, False),
    }
    hub = WindowsEventHub(native_api=_api(timezone_fingerprint))

    timezone_fingerprint["value"] = ("Tokyo Standard Time", -540, False)
    assert hub.interpret_message(10, 0) == ("clock_changed", None)
    assert hub.interpret_message(11, 0) is None


def test_display_notifications_are_coalesced(qtbot):
    hub = WindowsEventHub(native_api=_api())
    spy = QSignalSpy(hub.display_changed)

    for _ in range(5):
        hub._queue_display_changed()

    qtbot.waitUntil(lambda: spy.count() == 1, timeout=500)
    qtbot.wait(120)
    assert spy.count() == 1


class _Screen(QObject):
    geometryChanged = Signal()
    availableGeometryChanged = Signal()
    logicalDotsPerInchChanged = Signal()
    physicalDotsPerInchChanged = Signal()


class _ScreenApplication(QObject):
    screenAdded = Signal(object)
    screenRemoved = Signal(object)

    def __init__(self, screens):
        super().__init__()
        self._screens = list(screens)

    def screens(self):
        return list(self._screens)


def test_removed_screen_is_unwatched_before_shutdown():
    first = _Screen()
    second = _Screen()
    application = _ScreenApplication([first])
    hub = WindowsEventHub(native_api=_api())
    hub._install_screen_events(application)

    application._screens.append(second)
    application.screenAdded.emit(second)
    assert set(hub._watched_screens) == {id(first), id(second)}

    application._screens.remove(first)
    application.screenRemoved.emit(first)
    assert set(hub._watched_screens) == {id(second)}

    # Simulate Qt invalidating the removed C++ wrapper. Shutdown must not
    # retain or inspect it after screenRemoved has been delivered.
    first.deleteLater()
    hub._disconnect_screen_events()
    assert hub._watched_screens == {}
