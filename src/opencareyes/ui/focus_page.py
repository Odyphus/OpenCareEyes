"""Focus mode settings page."""

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


class FocusPage(QWidget):
    """Settings page for focus mode configuration."""

    def __init__(self, settings, focus_mode, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._focus_mode = focus_mode
        self._setup_ui()
        self._load_settings()
        self._connect_signals()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # Enable checkbox
        self._enable_cb = QCheckBox("启用专注模式")
        layout.addWidget(self._enable_cb)

        # Dim level group
        dim_group = QGroupBox("背景暗化级别")
        dim_layout = QVBoxLayout(dim_group)

        self._dim_label = QLabel()
        dim_layout.addWidget(self._dim_label)

        self._dim_slider = QSlider(Qt.Horizontal)
        self._dim_slider.setRange(0, 255)
        self._dim_slider.setSingleStep(5)
        self._dim_slider.setPageStep(20)
        dim_layout.addWidget(self._dim_slider)

        range_layout = QHBoxLayout()
        range_layout.addWidget(QLabel("0 (无暗化)"))
        range_layout.addStretch()
        range_layout.addWidget(QLabel("255 (全黑)"))
        dim_layout.addLayout(range_layout)

        layout.addWidget(dim_group)
        layout.addStretch()

    def _load_settings(self):
        self._enable_cb.setChecked(self._settings.focus_enabled)
        self._dim_slider.setValue(self._settings.focus_dim_level)
        self._update_dim_label(self._settings.focus_dim_level)

    def _connect_signals(self):
        self._enable_cb.toggled.connect(self._on_enable_toggled)
        self._dim_slider.valueChanged.connect(self._on_dim_changed)

    def _update_dim_label(self, value):
        self._dim_label.setText(f"当前暗化级别: {value}")

    def _on_enable_toggled(self, checked):
        self._settings.focus_enabled = checked
        if checked:
            self._focus_mode.enable()
        else:
            self._focus_mode.disable()

    def _on_dim_changed(self, value):
        self._update_dim_label(value)
        self._settings.focus_dim_level = value
        if self._settings.focus_enabled:
            self._focus_mode.set_dim_level(value)
