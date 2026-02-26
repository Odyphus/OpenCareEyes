"""General settings page."""

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QFormLayout,
    QCheckBox,
    QComboBox,
    QLineEdit,
    QDoubleSpinBox,
    QGroupBox,
    QLabel,
)

from opencareyes.constants import APP_NAME, APP_VERSION
from opencareyes.platform.autostart import (
    is_autostart_enabled,
    enable_autostart,
    disable_autostart,
)


class SettingsPage(QWidget):
    """General application settings page."""

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._setup_ui()
        self._load_settings()
        self._connect_signals()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # General group
        general_group = QGroupBox("常规")
        general_layout = QFormLayout(general_group)

        self._autostart_cb = QCheckBox("开机自动启动")
        general_layout.addRow(self._autostart_cb)

        self._theme_combo = QComboBox()
        self._theme_combo.addItem("暗色", "dark")
        self._theme_combo.addItem("亮色", "light")
        self._theme_combo.addItem("跟随系统", "system")
        general_layout.addRow("主题:", self._theme_combo)

        layout.addWidget(general_group)

        # Hotkeys group
        hotkey_group = QGroupBox("快捷键")
        hotkey_layout = QFormLayout(hotkey_group)

        self._hk_filter = QLineEdit()
        self._hk_filter.setReadOnly(True)
        hotkey_layout.addRow("蓝光过滤:", self._hk_filter)

        self._hk_dimmer = QLineEdit()
        self._hk_dimmer.setReadOnly(True)
        hotkey_layout.addRow("屏幕调光:", self._hk_dimmer)

        self._hk_break = QLineEdit()
        self._hk_break.setReadOnly(True)
        hotkey_layout.addRow("休息提醒:", self._hk_break)

        self._hk_focus = QLineEdit()
        self._hk_focus.setReadOnly(True)
        hotkey_layout.addRow("专注模式:", self._hk_focus)

        layout.addWidget(hotkey_group)

        # Location group
        loc_group = QGroupBox("位置 (用于日出日落计算)")
        loc_layout = QFormLayout(loc_group)

        self._lat_spin = QDoubleSpinBox()
        self._lat_spin.setRange(-90.0, 90.0)
        self._lat_spin.setDecimals(2)
        self._lat_spin.setSuffix(" °")
        loc_layout.addRow("纬度:", self._lat_spin)

        self._lon_spin = QDoubleSpinBox()
        self._lon_spin.setRange(-180.0, 180.0)
        self._lon_spin.setDecimals(2)
        self._lon_spin.setSuffix(" °")
        loc_layout.addRow("经度:", self._lon_spin)

        layout.addWidget(loc_group)

        # About group
        about_group = QGroupBox("关于")
        about_layout = QVBoxLayout(about_group)
        about_layout.addWidget(QLabel(f"{APP_NAME} v{APP_VERSION}"))
        about_layout.addWidget(QLabel("开源护眼工具"))
        layout.addWidget(about_group)

        layout.addStretch()

    def _load_settings(self):
        self._autostart_cb.setChecked(is_autostart_enabled())
        idx = self._theme_combo.findData(self._settings.theme)
        if idx >= 0:
            self._theme_combo.setCurrentIndex(idx)
        self._hk_filter.setText(self._settings.hotkey_filter)
        self._hk_dimmer.setText(self._settings.hotkey_dimmer)
        self._hk_break.setText(self._settings.hotkey_break)
        self._hk_focus.setText(self._settings.hotkey_focus)
        self._lat_spin.setValue(self._settings.latitude)
        self._lon_spin.setValue(self._settings.longitude)

    def _connect_signals(self):
        self._autostart_cb.toggled.connect(self._on_autostart_toggled)
        self._theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        self._lat_spin.valueChanged.connect(self._on_lat_changed)
        self._lon_spin.valueChanged.connect(self._on_lon_changed)

    def _on_autostart_toggled(self, checked):
        self._settings.autostart = checked
        if checked:
            enable_autostart()
        else:
            disable_autostart()

    def _on_theme_changed(self, index):
        theme = self._theme_combo.currentData()
        self._settings.theme = theme

    def _on_lat_changed(self, value):
        self._settings.latitude = value

    def _on_lon_changed(self, value):
        self._settings.longitude = value
