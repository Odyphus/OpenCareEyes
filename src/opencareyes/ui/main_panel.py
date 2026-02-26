"""Main settings panel with tabbed interface."""

from PySide6.QtWidgets import QWidget, QVBoxLayout, QTabWidget
from PySide6.QtCore import Qt

from opencareyes.ui.blue_light_page import BlueLightPage
from opencareyes.ui.dimmer_page import DimmerPage
from opencareyes.ui.break_page import BreakPage
from opencareyes.ui.focus_page import FocusPage
from opencareyes.ui.settings_page import SettingsPage


class MainPanel(QWidget):
    """Tabbed settings panel for all features."""

    def __init__(self, settings, blue_filter, dimmer, break_reminder, focus_mode, parent=None):
        super().__init__(parent)
        self._settings = settings
        self.setWindowTitle("OpenCareEyes 设置")
        self.setMinimumSize(600, 450)
        self.setWindowFlags(self.windowFlags() | Qt.Window)

        layout = QVBoxLayout(self)
        self._tabs = QTabWidget()

        self._blue_light_page = BlueLightPage(settings, blue_filter)
        self._dimmer_page = DimmerPage(settings, dimmer)
        self._break_page = BreakPage(settings, break_reminder)
        self._focus_page = FocusPage(settings, focus_mode)
        self._settings_page = SettingsPage(settings)

        self._tabs.addTab(self._blue_light_page, "蓝光过滤")
        self._tabs.addTab(self._dimmer_page, "屏幕调光")
        self._tabs.addTab(self._break_page, "休息提醒")
        self._tabs.addTab(self._focus_page, "专注模式")
        self._tabs.addTab(self._settings_page, "设置")

        layout.addWidget(self._tabs)

    def closeEvent(self, event):
        """Minimize to tray instead of closing."""
        event.ignore()
        self.hide()
