"""Regression tests for the first-run setup commit boundary."""

from __future__ import annotations

import os
import sys
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, QRect, Signal, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QBoxLayout, QDialog  # noqa: E402

from opencareyes.ui.onboarding import OnboardingDialog  # noqa: E402


class FakeController(QObject):
    operation_failed = Signal(str, str)

    def __init__(self, fail_on: str | None = None):
        super().__init__()
        self.fail_on = fail_on
        self.calls: list[str] = []
        self.completed = False

    def _call(self, name: str) -> bool:
        self.calls.append(name)
        if self.fail_on == name:
            self.operation_failed.emit(name, "模拟设置失败")
            return False
        return True

    def apply_display_profile(self, _profile: str) -> bool:
        return self._call("profile")

    def set_break_mode(self, _mode: str) -> bool:
        return self._call("break_mode")

    def set_feature_enabled(self, _feature: str, _enabled: bool) -> bool:
        if _feature == "dimmer":
            assert _enabled is False
        return self._call(_feature + "_enable")

    def set_autostart(self, _enabled: bool) -> bool:
        return self._call("autostart")

    def set_location(self, _latitude: float, _longitude: float, _city: str) -> bool:
        return self._call("location")

    def set_schedule(self, _enabled: bool, **_kwargs) -> bool:
        return self._call("schedule")

    def complete_onboarding(self) -> bool:
        if not self._call("complete"):
            return False
        self.completed = True
        return True


@pytest.fixture(scope="module")
def gui_app():
    app = QApplication.instance()
    if app is not None and not isinstance(app, QApplication):
        pytest.skip("A non-GUI QCoreApplication already exists")
    return app or QApplication(sys.argv)


@pytest.mark.parametrize(
    "fail_on",
    (
        "dimmer_enable",
        "break_mode",
        "breaks_enable",
        "autostart",
        "complete",
    ),
)
def test_failed_setup_command_keeps_dialog_open(gui_app, fail_on):
    controller = FakeController(fail_on)
    dialog = OnboardingDialog(controller)
    dialog._stack.setCurrentIndex(dialog._stack.count() - 1)

    dialog._advance()

    assert dialog.result() == QDialog.DialogCode.Rejected
    assert controller.completed is False
    assert controller.calls[-1] == fail_on
    if fail_on != "complete":
        assert "complete" not in controller.calls
    assert "模拟设置失败" in dialog._error_label.text()


def test_successful_setup_completes_before_closing(gui_app):
    controller = FakeController()
    dialog = OnboardingDialog(controller)
    dialog._stack.setCurrentIndex(dialog._stack.count() - 1)

    dialog._advance()

    assert controller.calls == [
        "dimmer_enable",
        "break_mode",
        "breaks_enable",
        "autostart",
        "complete",
    ]
    assert controller.completed is True
    assert dialog.result() == QDialog.DialogCode.Accepted


def test_setup_has_three_steps_and_never_configures_display_automation(gui_app):
    controller = FakeController()
    dialog = OnboardingDialog(controller)
    dialog._stack.setCurrentIndex(dialog._stack.count() - 1)

    dialog._advance()

    assert "location" not in controller.calls
    assert "schedule" not in controller.calls
    assert "profile" not in controller.calls
    assert dialog._stack.count() == 3
    assert controller.completed is True


def test_onboarding_fits_small_available_geometry_without_horizontal_scroll(
    qtbot,
    monkeypatch,
):
    monkeypatch.setattr(
        OnboardingDialog,
        "_available_geometry",
        lambda _self: QRect(0, 0, 683, 384),
    )
    dialog = OnboardingDialog(FakeController())
    qtbot.addWidget(dialog)
    dialog._stack.setCurrentIndex(1)
    dialog.show()
    qtbot.wait(1)

    assert dialog.width() <= 651
    assert dialog.height() <= 352
    assert dialog.minimumHeight() <= 352
    assert dialog._content_scroll.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
    assert dialog._content_scroll.horizontalScrollBar().maximum() == 0
    assert dialog._content_scroll.verticalScrollBar().maximum() > 0
    assert dialog._break_layout.direction() == QBoxLayout.TopToBottom
    assert dialog._next_button.isVisible()


def test_onboarding_applies_shared_theme_snapshot(gui_app):
    dialog = OnboardingDialog(FakeController())

    dialog.apply_theme(
        SimpleNamespace(resolved="dark", high_contrast=True)
    )

    assert dialog.property("resolvedTheme") == "dark"
    assert dialog.property("highContrast") is True
