"""Visible failure handling for display-overlay recovery."""

from PySide6.QtTest import QSignalSpy

from opencareyes.core.focus_mode import FocusMode
from opencareyes.core.screen_dimmer import ScreenDimmer


def test_dimmer_overlay_creation_failure_is_reported(monkeypatch, qtbot):
    dimmer = ScreenDimmer()
    spy = QSignalSpy(dimmer.operation_failed)
    monkeypatch.setattr(dimmer, "_create_overlays", lambda: False)

    assert dimmer.enable(80) is False
    assert dimmer.enabled is False
    assert spy.count() == 1
    assert spy.at(0)[0] == "dimmer_overlay_failed"


def test_focus_overlay_creation_failure_is_reported(monkeypatch, qtbot):
    focus = FocusMode()
    spy = QSignalSpy(focus.operation_failed)
    monkeypatch.setattr(focus, "_create_overlays", lambda: False)

    assert focus.enable() is False
    assert focus.enabled is False
    assert spy.count() == 1
    assert spy.at(0)[0] == "focus_overlay_failed"
