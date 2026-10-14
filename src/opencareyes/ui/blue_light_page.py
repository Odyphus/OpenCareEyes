"""Windows Night Light entry point and independent app-owned dimming."""

from __future__ import annotations

from PySide6.QtCore import QSignalBlocker, Qt, QTimer
from PySide6.QtWidgets import (
    QBoxLayout, QCheckBox, QHBoxLayout, QLabel, QPushButton, QSlider,
)

from opencareyes.constants import DIM_MAX
from opencareyes.ui.widgets import (
    Card, PageHeader, ScrollPage, first_state_value, set_accessible,
)


class BlueLightPage(ScrollPage):
    """Keep Windows colour settings separate from the app's dimming controls."""

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self._controller = controller
        self._preview_dim = 0
        self._dim_timer = QTimer(self)
        self._dim_timer.setSingleShot(True)
        self._dim_timer.setInterval(50)
        self._dim_timer.timeout.connect(self._send_dim_preview)
        self._build_ui()
        self._connect_signals()
        self.render(controller.state)

    def _build_ui(self) -> None:
        self.layout.addWidget(PageHeader(
            "屏幕舒适度", "色温交给 Windows，屏幕调暗只由你手动控制。",
        ))
        night_card = Card(
            "Windows 夜间模式", "在系统设置中开启夜间模式、调整暖色强度和定时。",
        )
        night_row = self._night_row = QBoxLayout(QBoxLayout.LeftToRight)
        night_copy = QLabel("系统夜间模式独立运行，软件不会自动改变屏幕明暗。")
        night_copy.setObjectName("cardDescription")
        night_copy.setWordWrap(True)
        self._night_light_button = QPushButton("打开 Windows 夜间模式")
        self._night_light_button.setObjectName("secondaryButton")
        self._night_light_button.setMinimumHeight(40)
        self._night_light_button.setStyleSheet("QPushButton { min-height: 28px; }")
        opener = getattr(self._controller, "open_windows_night_light", None)
        self._night_light_button.setEnabled(callable(opener))
        if callable(opener):
            self._night_light_button.clicked.connect(opener)
        set_accessible(self._night_light_button, "打开 Windows 夜间模式设置")
        night_row.addWidget(night_copy, 1)
        night_row.addWidget(self._night_light_button)
        night_card.body.addLayout(night_row)
        self.layout.addWidget(night_card)

        profile_card = Card(
            "手动调暗", "默认关闭。开启后按需调整；不会随时间或应用自动切换。",
        )
        dim_top = QHBoxLayout()
        self._dimmer_toggle = QCheckBox("启用屏幕调暗")
        set_accessible(self._dimmer_toggle, "启用屏幕调暗")
        self._dim_value = QLabel("0%")
        self._dim_value.setObjectName("accentValue")
        dim_top.addWidget(self._dimmer_toggle)
        dim_top.addStretch()
        dim_top.addWidget(self._dim_value)
        profile_card.body.addLayout(dim_top)
        self._dim_slider = QSlider(Qt.Horizontal)
        self._dim_slider.setRange(0, 100)
        self._dim_slider.setSingleStep(1)
        self._dim_slider.setPageStep(10)
        set_accessible(self._dim_slider, "屏幕调暗百分比", "0% 为不调暗，100% 为最暗")
        profile_card.body.addWidget(self._dim_slider)
        dim_range = QHBoxLayout()
        dim_range.addWidget(QLabel("0%  不调暗"))
        dim_range.addStretch()
        dim_range.addWidget(QLabel("100%  最暗"))
        profile_card.body.addLayout(dim_range)
        self.layout.addWidget(profile_card)

        health_card = Card("软件显示状态")
        health_row = self._health_row = QBoxLayout(QBoxLayout.LeftToRight)
        self._health_label = QLabel()
        self._health_label.setObjectName("sectionLead")
        self._health_label.setWordWrap(True)
        self._restore_button = QPushButton("关闭软件显示效果")
        self._restore_button.setObjectName("quietButton")
        restore = getattr(self._controller, "restore_display_effects", None)
        self._restore_button.setEnabled(callable(restore))
        if callable(restore):
            self._restore_button.clicked.connect(restore)
        self._restore_button.setToolTip("关闭软件的调暗和专注遮罩；Windows 夜间模式由系统设置管理。")
        health_row.addWidget(self._health_label, 1)
        health_row.addWidget(self._restore_button)
        health_card.body.addLayout(health_row)
        self.layout.addWidget(health_card)
        self.layout.addStretch()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        compact = self.viewport().width() < 600
        direction = QBoxLayout.TopToBottom if compact else QBoxLayout.LeftToRight
        self._night_row.setDirection(direction)
        self._health_row.setDirection(direction)

    def _connect_signals(self) -> None:
        self._dimmer_toggle.toggled.connect(
            lambda enabled: self._controller.set_feature_enabled("dimmer", enabled)
        )
        self._dim_slider.valueChanged.connect(self._on_dim_changed)
        self._dim_slider.sliderReleased.connect(self._commit_dim)
        self._controller.state_changed.connect(self.render)

    def _on_dim_changed(self, percent: int) -> None:
        self._preview_dim = round(percent * DIM_MAX / 100)
        self._dim_value.setText(f"{percent}%")
        self._dim_slider.setAccessibleDescription(f"当前调暗 {percent}%")
        if self._dim_slider.isSliderDown():
            self._dim_timer.start()
        else:
            self._commit_dim()

    def _send_dim_preview(self) -> None:
        self._controller.set_dim_level(self._preview_dim, persist=False)

    def _commit_dim(self) -> None:
        self._dim_timer.stop()
        self._controller.set_dim_level(self._preview_dim, persist=True)

    def render(self, state) -> None:
        dimmer_enabled = bool(first_state_value(state, "display.dimmer_enabled", default=False))
        dim_level = int(first_state_value(state, "display.dim_level", default=0))
        pending = bool(first_state_value(state, "display_health.pending", default=False))
        status = str(first_state_value(state, "display_health.status", default="ok"))
        message = str(first_state_value(state, "display_health.message", default=""))
        with QSignalBlocker(self._dimmer_toggle):
            self._dimmer_toggle.setChecked(dimmer_enabled)
        if not self._dim_slider.isSliderDown():
            percent = round(dim_level * 100 / max(1, DIM_MAX))
            with QSignalBlocker(self._dim_slider):
                self._dim_slider.setValue(percent)
            self._preview_dim = dim_level
            self._dim_value.setText(f"{percent}%")
        if pending:
            self._health_label.setText("正在应用软件显示效果…")
        elif status in {"error", "failed", "unavailable"}:
            self._health_label.setText(message or "软件显示效果暂时不可用。")
        else:
            effective = bool(first_state_value(
                state, "effective_policy.dimmer.effective_enabled", default=dimmer_enabled,
            ))
            if dimmer_enabled and not effective:
                text = "屏幕调暗已暂停，恢复全部效果后继续。"
            elif dimmer_enabled and dim_level == 0:
                text = "屏幕调暗已开启 · 当前 0%，屏幕未调暗。"
            elif dimmer_enabled:
                text = f"手动调暗 {round(dim_level * 100 / max(1, DIM_MAX))}%"
            else:
                text = "屏幕调暗已关闭，调整滑块不会自动开启。"
            self._health_label.setText(text)
        available = bool(first_state_value(state, "capabilities.dimmer_available", default=True))
        self._dimmer_toggle.setEnabled(available)
        self._dim_slider.setEnabled(available and not pending)



ScreenComfortPage = BlueLightPage
