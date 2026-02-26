"""Blue light filter settings page."""

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QCheckBox,
    QSlider,
    QLabel,
    QPushButton,
    QGroupBox,
)
from PySide6.QtCore import Qt

from opencareyes.constants import TEMP_MIN, TEMP_MAX
from opencareyes.config.presets import PRESETS


class BlueLightPage(QWidget):
    """Settings page for blue light filter configuration."""

    def __init__(self, settings, blue_filter, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._blue_filter = blue_filter
        self._setup_ui()
        self._load_settings()
        self._connect_signals()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # Enable checkbox
        self._enable_cb = QCheckBox("启用蓝光过滤")
        layout.addWidget(self._enable_cb)

        # Temperature group
        temp_group = QGroupBox("色温调节")
        temp_layout = QVBoxLayout(temp_group)

        self._temp_label = QLabel()
        temp_layout.addWidget(self._temp_label)

        self._temp_slider = QSlider(Qt.Horizontal)
        self._temp_slider.setRange(TEMP_MIN, TEMP_MAX)
        self._temp_slider.setSingleStep(100)
        self._temp_slider.setPageStep(500)
        temp_layout.addWidget(self._temp_slider)

        # Min/max labels
        range_layout = QHBoxLayout()
        range_layout.addWidget(QLabel(f"{TEMP_MIN}K (暖色)"))
        range_layout.addStretch()
        range_layout.addWidget(QLabel(f"{TEMP_MAX}K (冷色)"))
        temp_layout.addLayout(range_layout)

        layout.addWidget(temp_group)

        # Preset buttons group
        preset_group = QGroupBox("快捷预设")
        preset_layout = QHBoxLayout(preset_group)
        self._preset_buttons = {}
        for name, info in PRESETS.items():
            if name == "custom":
                continue
            btn = QPushButton(info["desc"].split(" - ")[0])
            btn.setToolTip(info["desc"])
            btn.clicked.connect(lambda checked=False, n=name: self._apply_preset(n))
            preset_layout.addWidget(btn)
            self._preset_buttons[name] = btn
        layout.addWidget(preset_group)

        # Schedule toggle
        self._schedule_cb = QCheckBox("启用日出日落自动调节")
        layout.addWidget(self._schedule_cb)

        layout.addStretch()

    def _load_settings(self):
        self._enable_cb.setChecked(self._settings.filter_enabled)
        self._temp_slider.setValue(self._settings.color_temperature)
        self._schedule_cb.setChecked(self._settings.filter_schedule_enabled)
        self._update_temp_label(self._settings.color_temperature)

    def _connect_signals(self):
        self._enable_cb.toggled.connect(self._on_enable_toggled)
        self._temp_slider.valueChanged.connect(self._on_temp_changed)
        self._schedule_cb.toggled.connect(self._on_schedule_toggled)

    def _update_temp_label(self, value):
        self._temp_label.setText(f"当前色温: {value}K")

    def _on_enable_toggled(self, checked):
        self._settings.filter_enabled = checked
        if checked:
            self._blue_filter.enable(self._temp_slider.value())
        else:
            self._blue_filter.disable()

    def _on_temp_changed(self, value):
        self._update_temp_label(value)
        self._settings.color_temperature = value
        if self._settings.filter_enabled:
            self._blue_filter.set_temperature(value)

    def _on_schedule_toggled(self, checked):
        self._settings.filter_schedule_enabled = checked

    def _apply_preset(self, name):
        preset = PRESETS[name]
        self._temp_slider.setValue(preset["temp"])
        self._settings.current_preset = name
