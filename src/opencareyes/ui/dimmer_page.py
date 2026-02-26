"""Screen dimmer settings page."""

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QCheckBox,
    QSlider,
    QLabel,
    QGroupBox,
)
from PySide6.QtCore import Qt

from opencareyes.constants import DIM_MIN, DIM_MAX


class DimmerPage(QWidget):
    """Settings page for screen dimmer configuration."""

    def __init__(self, settings, dimmer, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._dimmer = dimmer
        self._setup_ui()
        self._load_settings()
        self._connect_signals()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # Enable checkbox
        self._enable_cb = QCheckBox("启用屏幕调光")
        layout.addWidget(self._enable_cb)

        # Brightness group
        dim_group = QGroupBox("亮度调节")
        dim_layout = QVBoxLayout(dim_group)

        self._dim_label = QLabel()
        dim_layout.addWidget(self._dim_label)

        self._dim_slider = QSlider(Qt.Horizontal)
        self._dim_slider.setRange(DIM_MIN, DIM_MAX)
        self._dim_slider.setSingleStep(5)
        self._dim_slider.setPageStep(20)
        dim_layout.addWidget(self._dim_slider)

        range_layout = QHBoxLayout()
        range_layout.addWidget(QLabel(f"{DIM_MIN} (无调光)"))
        range_layout.addStretch()
        range_layout.addWidget(QLabel(f"{DIM_MAX} (最暗)"))
        dim_layout.addLayout(range_layout)

        layout.addWidget(dim_group)
        layout.addStretch()

    def _load_settings(self):
        self._enable_cb.setChecked(self._settings.dimmer_enabled)
        self._dim_slider.setValue(self._settings.dim_level)
        self._update_dim_label(self._settings.dim_level)

    def _connect_signals(self):
        self._enable_cb.toggled.connect(self._on_enable_toggled)
        self._dim_slider.valueChanged.connect(self._on_dim_changed)

    def _update_dim_label(self, value):
        self._dim_label.setText(f"当前调光级别: {value}")

    def _on_enable_toggled(self, checked):
        self._settings.dimmer_enabled = checked
        if checked:
            self._dimmer.enable(self._dim_slider.value())
        else:
            self._dimmer.disable()

    def _on_dim_changed(self, value):
        self._update_dim_label(value)
        self._settings.dim_level = value
        if self._settings.dimmer_enabled:
            self._dimmer.set_brightness(value)
