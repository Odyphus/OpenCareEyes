"""Break reminder settings page."""

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QFormLayout,
    QCheckBox,
    QComboBox,
    QSpinBox,
    QGroupBox,
)


BREAK_MODES = {
    "pomodoro": "番茄钟",
    "20-20-20": "20-20-20",
    "custom": "自定义",
}


class BreakPage(QWidget):
    """Settings page for break reminder configuration."""

    def __init__(self, settings, break_reminder, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._break_reminder = break_reminder
        self._setup_ui()
        self._load_settings()
        self._connect_signals()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # Enable checkbox
        self._enable_cb = QCheckBox("启用休息提醒")
        layout.addWidget(self._enable_cb)

        # Mode group
        mode_group = QGroupBox("提醒模式")
        mode_layout = QFormLayout(mode_group)

        self._mode_combo = QComboBox()
        for key, label in BREAK_MODES.items():
            self._mode_combo.addItem(label, key)
        mode_layout.addRow("模式:", self._mode_combo)
        layout.addWidget(mode_group)

        # Duration group
        dur_group = QGroupBox("时间设置")
        dur_layout = QFormLayout(dur_group)

        self._work_spin = QSpinBox()
        self._work_spin.setRange(1, 120)
        self._work_spin.setSuffix(" 分钟")
        dur_layout.addRow("工作时长:", self._work_spin)

        self._break_spin = QSpinBox()
        self._break_spin.setRange(1, 60)
        dur_layout.addRow("休息时长:", self._break_spin)

        layout.addWidget(dur_group)

        # Force break
        self._force_cb = QCheckBox("强制休息 (锁定屏幕)")
        layout.addWidget(self._force_cb)

        layout.addStretch()

    def _load_settings(self):
        self._enable_cb.setChecked(self._settings.break_enabled)
        idx = self._mode_combo.findData(self._settings.break_mode)
        if idx >= 0:
            self._mode_combo.setCurrentIndex(idx)
        self._work_spin.setValue(self._settings.work_duration // 60)
        self._force_cb.setChecked(self._settings.force_break)
        # Must update break_spin AFTER setting mode but BEFORE connecting signals
        # to avoid triggering valueChanged which overwrites settings
        self._update_break_spin_for_mode(self._settings.break_mode)

    def _connect_signals(self):
        self._enable_cb.toggled.connect(self._on_enable_toggled)
        self._mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        self._work_spin.valueChanged.connect(self._on_work_changed)
        self._break_spin.valueChanged.connect(self._on_break_changed)
        self._force_cb.toggled.connect(self._on_force_toggled)

    def _update_break_spin_for_mode(self, mode):
        if mode == "20-20-20":
            self._break_spin.setSuffix(" 秒")
            self._break_spin.setRange(5, 120)
            self._break_spin.setValue(self._settings.break_duration)
        else:
            self._break_spin.setSuffix(" 分钟")
            self._break_spin.setRange(1, 60)
            self._break_spin.setValue(self._settings.break_duration // 60)

    def _on_enable_toggled(self, checked):
        self._settings.break_enabled = checked
        if checked:
            self._break_reminder.start()
        else:
            self._break_reminder.stop()

    def _on_mode_changed(self, index):
        mode = self._mode_combo.currentData()
        self._settings.break_mode = mode
        self._update_break_spin_for_mode(mode)
        if mode == "pomodoro":
            self._work_spin.setValue(25)
            self._break_spin.setValue(5)
        elif mode == "20-20-20":
            self._work_spin.setValue(20)
            self._break_spin.setValue(20)

    def _on_work_changed(self, value):
        self._settings.work_duration = value * 60
        self._break_reminder.set_work_duration(value * 60)

    def _on_break_changed(self, value):
        mode = self._mode_combo.currentData()
        if mode == "20-20-20":
            self._settings.break_duration = value
            self._break_reminder.set_break_duration(value)
        else:
            self._settings.break_duration = value * 60
            self._break_reminder.set_break_duration(value * 60)

    def _on_force_toggled(self, checked):
        self._settings.force_break = checked
        self._break_reminder.force_break = checked
