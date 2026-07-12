"""Screen comfort page: colour temperature, dimming, and display profiles."""

from __future__ import annotations

from PySide6.QtCore import QSignalBlocker, Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
)

from opencareyes.constants import DIM_MAX, TEMP_MAX, TEMP_MIN
from opencareyes.ui.widgets import (
    Card,
    PageHeader,
    ScrollPage,
    first_state_value,
    set_accessible,
    temperature_description,
)


_PROFILES = (
    ("office", "办公", "自然色温，适合日常工作"),
    ("reading", "阅读", "偏暖且轻微调暗"),
    ("night", "夜间", "暖色并降低屏幕亮度"),
    ("game", "游戏", "保持较清爽的画面"),
)


class BlueLightPage(ScrollPage):
    """Unified screen-comfort page backed only by ``AppController`` commands."""

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self._controller = controller
        self._preview_temperature = TEMP_MAX
        self._preview_dim = 0

        self._temperature_timer = QTimer(self)
        self._temperature_timer.setSingleShot(True)
        self._temperature_timer.setInterval(50)
        self._temperature_timer.timeout.connect(self._send_temperature_preview)

        self._dim_timer = QTimer(self)
        self._dim_timer.setSingleShot(True)
        self._dim_timer.setInterval(50)
        self._dim_timer.timeout.connect(self._send_dim_preview)

        self._build_ui()
        self._connect_signals()
        self.render(controller.state)

    def _build_ui(self) -> None:
        self.layout.addWidget(PageHeader(
            "屏幕舒适度",
            "调节夜间色温与屏幕明暗，改善主观观看舒适度。显示方案不会改变休息或专注设置。",
        ))

        profile_card = Card("显示方案", "一键应用常用组合，之后仍可微调。")
        profile_grid = QGridLayout()
        profile_grid.setHorizontalSpacing(10)
        profile_grid.setVerticalSpacing(10)
        self._profile_buttons: dict[str, QPushButton] = {}
        for index, (key, label, description) in enumerate(_PROFILES):
            button = QPushButton(label)
            button.setObjectName("profileButton")
            button.setCheckable(True)
            button.setToolTip(description)
            set_accessible(button, f"应用{label}显示方案", description)
            button.clicked.connect(
                lambda checked=False, profile=key: self._controller.apply_display_profile(profile)
            )
            profile_grid.addWidget(button, index // 2, index % 2)
            self._profile_buttons[key] = button
        profile_card.body.addLayout(profile_grid)
        self.layout.addWidget(profile_card)

        temperature_card = Card("色温", "数值越低，画面越偏暖。")
        temperature_top = QHBoxLayout()
        self._filter_toggle = QCheckBox("启用色温调节")
        set_accessible(self._filter_toggle, "启用色温调节")
        self._temperature_value = QLabel()
        self._temperature_value.setObjectName("warmValue")
        temperature_top.addWidget(self._filter_toggle)
        temperature_top.addStretch()
        temperature_top.addWidget(self._temperature_value)
        temperature_card.body.addLayout(temperature_top)

        self._temperature_slider = QSlider(Qt.Horizontal)
        self._temperature_slider.setRange(TEMP_MIN, TEMP_MAX)
        self._temperature_slider.setSingleStep(100)
        self._temperature_slider.setPageStep(500)
        self._temperature_slider.setTickInterval(500)
        set_accessible(
            self._temperature_slider,
            "色温",
            f"可调范围 {TEMP_MIN} 至 {TEMP_MAX} Kelvin",
        )
        temperature_card.body.addWidget(self._temperature_slider)
        temperature_range = QHBoxLayout()
        minimum = QLabel(f"暖色  {TEMP_MIN}K")
        maximum = QLabel(f"清爽  {TEMP_MAX}K")
        minimum.setObjectName("rangeHint")
        maximum.setObjectName("rangeHint")
        temperature_range.addWidget(minimum)
        temperature_range.addStretch()
        temperature_range.addWidget(maximum)
        temperature_card.body.addLayout(temperature_range)
        self.layout.addWidget(temperature_card)

        dim_card = Card("屏幕调暗", "在系统最低亮度仍然刺眼时，叠加柔和的调暗效果。")
        dim_top = QHBoxLayout()
        self._dimmer_toggle = QCheckBox("启用屏幕调暗")
        set_accessible(self._dimmer_toggle, "启用屏幕调暗")
        self._dim_value = QLabel("0%")
        self._dim_value.setObjectName("accentValue")
        dim_top.addWidget(self._dimmer_toggle)
        dim_top.addStretch()
        dim_top.addWidget(self._dim_value)
        dim_card.body.addLayout(dim_top)

        self._dim_slider = QSlider(Qt.Horizontal)
        self._dim_slider.setRange(0, 100)
        self._dim_slider.setSingleStep(1)
        self._dim_slider.setPageStep(10)
        set_accessible(self._dim_slider, "屏幕调暗百分比", "0% 为不调暗，100% 为最暗")
        dim_card.body.addWidget(self._dim_slider)
        dim_range = QHBoxLayout()
        dim_range.addWidget(QLabel("0%  不调暗"))
        dim_range.addStretch()
        dim_range.addWidget(QLabel("100%  最暗"))
        dim_card.body.addLayout(dim_range)
        self.layout.addWidget(dim_card)
        self.layout.addStretch()

    def _connect_signals(self) -> None:
        self._filter_toggle.toggled.connect(
            lambda enabled: self._controller.set_feature_enabled("filter", enabled)
        )
        self._dimmer_toggle.toggled.connect(
            lambda enabled: self._controller.set_feature_enabled("dimmer", enabled)
        )
        self._temperature_slider.valueChanged.connect(self._on_temperature_changed)
        self._temperature_slider.sliderReleased.connect(self._commit_temperature)
        self._dim_slider.valueChanged.connect(self._on_dim_changed)
        self._dim_slider.sliderReleased.connect(self._commit_dim)
        self._controller.state_changed.connect(self.render)

    def _on_temperature_changed(self, value: int) -> None:
        self._preview_temperature = value
        self._update_temperature_label(value)
        if self._temperature_slider.isSliderDown():
            self._temperature_timer.start()

    def _send_temperature_preview(self) -> None:
        self._controller.set_color_temperature(self._preview_temperature, persist=False)

    def _commit_temperature(self) -> None:
        self._temperature_timer.stop()
        self._controller.set_color_temperature(self._temperature_slider.value(), persist=True)

    def _on_dim_changed(self, percent: int) -> None:
        self._preview_dim = round(percent * DIM_MAX / 100)
        self._dim_value.setText(f"{percent}%")
        self._dim_slider.setAccessibleDescription(f"当前调暗 {percent}%")
        if self._dim_slider.isSliderDown():
            self._dim_timer.start()

    def _send_dim_preview(self) -> None:
        try:
            self._controller.set_dim_level(self._preview_dim, persist=False)
        except TypeError:
            self._controller.set_dim_level(self._preview_dim)

    def _commit_dim(self) -> None:
        self._dim_timer.stop()
        try:
            self._controller.set_dim_level(self._preview_dim, persist=True)
        except TypeError:
            self._controller.set_dim_level(self._preview_dim)

    def _update_temperature_label(self, value: int) -> None:
        self._temperature_value.setText(f"{temperature_description(value)} · {value}K")
        self._temperature_slider.setAccessibleDescription(
            f"当前为{temperature_description(value)}，{value} Kelvin"
        )

    def render(self, state) -> None:
        filter_enabled = bool(first_state_value(
            state, "display.filter_enabled", "display.enabled", default=False
        ))
        dimmer_enabled = bool(first_state_value(
            state, "display.dimmer_enabled", default=False
        ))
        temperature = int(first_state_value(
            state, "display.color_temperature", "display.temperature", default=TEMP_MAX
        ))
        dim_level = int(first_state_value(state, "display.dim_level", default=0))
        preset = str(first_state_value(state, "display.preset", "display.profile", default="custom"))
        capabilities_filter = bool(first_state_value(
            state, "capabilities.filter_available", default=True
        ))
        capabilities_dimmer = bool(first_state_value(
            state, "capabilities.dimmer_available", default=True
        ))

        with QSignalBlocker(self._filter_toggle):
            self._filter_toggle.setChecked(filter_enabled)
        with QSignalBlocker(self._dimmer_toggle):
            self._dimmer_toggle.setChecked(dimmer_enabled)
        if not self._temperature_slider.isSliderDown():
            with QSignalBlocker(self._temperature_slider):
                self._temperature_slider.setValue(temperature)
            self._preview_temperature = temperature
            self._update_temperature_label(temperature)
        if not self._dim_slider.isSliderDown():
            percent = round(dim_level * 100 / max(1, DIM_MAX))
            with QSignalBlocker(self._dim_slider):
                self._dim_slider.setValue(percent)
            self._preview_dim = dim_level
            self._dim_value.setText(f"{percent}%")

        self._filter_toggle.setEnabled(capabilities_filter)
        self._temperature_slider.setEnabled(capabilities_filter)
        self._dimmer_toggle.setEnabled(capabilities_dimmer)
        self._dim_slider.setEnabled(capabilities_dimmer)
        for name, button in self._profile_buttons.items():
            with QSignalBlocker(button):
                button.setChecked(name == preset)


# Product terminology changed in v0.2, but retain the import used by older code.
ScreenComfortPage = BlueLightPage
