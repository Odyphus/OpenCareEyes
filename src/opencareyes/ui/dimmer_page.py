"""Standalone dimmer page kept for API compatibility.

The v0.2 main window presents dimming together with colour temperature on the
screen-comfort page.  This widget remains useful for embedding and tests.
"""

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QSlider

from opencareyes.constants import DIM_MAX
from opencareyes.ui.widgets import Card, PageHeader, ScrollPage, first_state_value, set_accessible


class DimmerPage(ScrollPage):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self._controller = controller
        self.layout.addWidget(PageHeader(
            "屏幕调暗",
            "在系统亮度之外叠加柔和调暗效果，适合夜间与低照度环境。",
        ))
        card = Card("调暗强度")
        top = QHBoxLayout()
        self._toggle = QCheckBox("启用屏幕调暗")
        self._value = QLabel("0%")
        self._value.setObjectName("accentValue")
        top.addWidget(self._toggle)
        top.addStretch()
        top.addWidget(self._value)
        card.body.addLayout(top)
        self._slider = QSlider(Qt.Horizontal)
        self._slider.setRange(0, 100)
        set_accessible(self._slider, "屏幕调暗百分比")
        card.body.addWidget(self._slider)
        self.layout.addWidget(card)
        self.layout.addStretch()

        self._toggle.toggled.connect(
            lambda enabled: self._controller.set_feature_enabled("dimmer", enabled)
        )
        self._slider.valueChanged.connect(lambda value: self._value.setText(f"{value}%"))
        self._slider.sliderReleased.connect(self._commit)
        self._controller.state_changed.connect(self.render)
        self.render(self._controller.state)

    def _commit(self) -> None:
        self._controller.set_dim_level(round(self._slider.value() * DIM_MAX / 100))

    def render(self, state) -> None:
        enabled = bool(first_state_value(state, "display.dimmer_enabled", default=False))
        level = int(first_state_value(state, "display.dim_level", default=0))
        percent = round(level * 100 / max(1, DIM_MAX))
        with QSignalBlocker(self._toggle):
            self._toggle.setChecked(enabled)
        if not self._slider.isSliderDown():
            with QSignalBlocker(self._slider):
                self._slider.setValue(percent)
            self._value.setText(f"{percent}%")
