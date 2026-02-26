"""System tray icon with context menu."""

import os
from PySide6.QtWidgets import QSystemTrayIcon, QMenu, QApplication
from PySide6.QtGui import QIcon, QPixmap, QColor, QAction
from PySide6.QtCore import Qt

from opencareyes.config.presets import PRESETS
from opencareyes.platform.autostart import is_autostart_enabled, enable_autostart, disable_autostart
from opencareyes.constants import ICONS_DIR

try:
    import darkdetect
    _HAS_DARKDETECT = True
except ImportError:
    _HAS_DARKDETECT = False


class TrayIcon(QSystemTrayIcon):
    """System tray icon with context menu for quick access."""

    def __init__(self, settings, blue_filter, dimmer, break_reminder, focus_mode, panel, mini_countdown=None):
        super().__init__()
        self._settings = settings
        self._blue_filter = blue_filter
        self._dimmer = dimmer
        self._break_reminder = break_reminder
        self._focus_mode = focus_mode
        self._panel = panel
        self._mini_countdown = mini_countdown

        self._create_icon()
        self._create_menu()
        self.activated.connect(self._on_activated)

        # Connect to break reminder tick to update tooltip
        self._break_reminder.tick.connect(self._on_break_tick)

    def _create_icon(self):
        """Create tray icon based on system theme."""
        # Detect system theme
        is_dark = True  # Default to dark
        if _HAS_DARKDETECT:
            try:
                theme = darkdetect.theme()
                is_dark = (theme == 'Dark')
            except Exception:
                pass

        # Load appropriate icon
        icon_name = 'tray_dark.png' if is_dark else 'tray_light.png'
        icon_path = os.path.join(ICONS_DIR, icon_name)

        if os.path.exists(icon_path):
            self.setIcon(QIcon(icon_path))
        else:
            # Fallback to colored placeholder
            pixmap = QPixmap(32, 32)
            pixmap.fill(QColor(70, 130, 220) if is_dark else QColor(50, 100, 180))
            self.setIcon(QIcon(pixmap))

        self.setToolTip("OpenCareEyes")

    def _create_menu(self):
        menu = QMenu()

        # Filter toggle
        self._filter_action = QAction()
        self._update_filter_text()
        self._filter_action.triggered.connect(self.toggle_filter)
        menu.addAction(self._filter_action)

        # Dimmer toggle
        self._dimmer_action = QAction()
        self._update_dimmer_text()
        self._dimmer_action.triggered.connect(self.toggle_dimmer)
        menu.addAction(self._dimmer_action)

        # Break toggle
        self._break_action = QAction()
        self._update_break_text()
        self._break_action.triggered.connect(self.toggle_break)
        menu.addAction(self._break_action)

        # Focus toggle
        self._focus_action = QAction()
        self._update_focus_text()
        self._focus_action.triggered.connect(self.toggle_focus)
        menu.addAction(self._focus_action)

        menu.addSeparator()

        # Presets submenu
        preset_menu = QMenu("预设模式", menu)
        for name, info in PRESETS.items():
            action = preset_menu.addAction(info["desc"])
            action.triggered.connect(lambda checked=False, n=name: self.apply_preset(n))
        menu.addMenu(preset_menu)

        menu.addSeparator()

        # Settings
        settings_action = menu.addAction("设置...")
        settings_action.triggered.connect(self._show_panel)

        # Autostart
        self._autostart_action = QAction("开机自启", menu)
        self._autostart_action.setCheckable(True)
        self._autostart_action.setChecked(is_autostart_enabled())
        self._autostart_action.toggled.connect(self._on_autostart_toggled)
        menu.addAction(self._autostart_action)

        # Quit
        quit_action = menu.addAction("退出")
        quit_action.triggered.connect(QApplication.quit)

        self.setContextMenu(menu)

    # ---- Toggle methods ----

    def toggle_filter(self):
        enabled = not self._settings.filter_enabled
        self._settings.filter_enabled = enabled
        if enabled:
            self._blue_filter.enable(self._settings.color_temperature)
        else:
            self._blue_filter.disable()
        self._update_filter_text()

    def toggle_dimmer(self):
        enabled = not self._settings.dimmer_enabled
        self._settings.dimmer_enabled = enabled
        if enabled:
            self._dimmer.enable(self._settings.dim_level)
        else:
            self._dimmer.disable()
        self._update_dimmer_text()

    def toggle_break(self):
        enabled = not self._settings.break_enabled
        self._settings.break_enabled = enabled
        if enabled:
            self._break_reminder.start()
        else:
            self._break_reminder.stop()
        self._update_break_text()
        # Update mini countdown visibility
        if self._mini_countdown:
            if enabled:
                from PySide6.QtWidgets import QApplication
                screen = QApplication.primaryScreen().geometry()
                self._mini_countdown.move(screen.width() - 160, screen.height() - 100)
                self._mini_countdown.show()
            else:
                self._mini_countdown.hide()

    def toggle_focus(self):
        enabled = not self._settings.focus_enabled
        self._settings.focus_enabled = enabled
        if enabled:
            self._focus_mode.enable()
        else:
            self._focus_mode.disable()
        self._update_focus_text()

    def apply_preset(self, name):
        preset = PRESETS[name]
        self._settings.current_preset = name
        self._settings.color_temperature = preset["temp"]
        self._settings.dim_level = preset["dim"]
        if not self._settings.filter_enabled:
            self._settings.filter_enabled = True
        self._blue_filter.enable(preset["temp"])
        if preset["dim"] > 0:
            self._settings.dimmer_enabled = True
            self._dimmer.enable(preset["dim"])
        self._update_filter_text()
        self._update_dimmer_text()

    # ---- Text updates ----

    def _update_filter_text(self):
        if self._settings.filter_enabled:
            temp = self._settings.color_temperature
            self._filter_action.setText(f"蓝光过滤: 开 ({temp}K)")
        else:
            self._filter_action.setText("蓝光过滤: 关")

    def _update_dimmer_text(self):
        if self._settings.dimmer_enabled:
            level = self._settings.dim_level
            self._dimmer_action.setText(f"屏幕调光: 开 ({level})")
        else:
            self._dimmer_action.setText("屏幕调光: 关")

    def _update_break_text(self):
        if self._settings.break_enabled:
            if self._break_reminder.enabled and not self._break_reminder.is_on_break:
                remaining = self._break_reminder.remaining
                minutes, seconds = divmod(remaining, 60)
                self._break_action.setText(f"休息提醒: 开 (工作 {minutes}:{seconds:02d})")
            elif self._break_reminder.is_on_break:
                self._break_action.setText("休息提醒: 开 (休息中)")
            else:
                self._break_action.setText("休息提醒: 开")
        else:
            self._break_action.setText("休息提醒: 关")

    def _update_focus_text(self):
        if self._settings.focus_enabled:
            self._focus_action.setText("专注模式: 开")
        else:
            self._focus_action.setText("专注模式: 关")

    # ---- Helpers ----

    def _show_panel(self):
        self._panel.show()
        self._panel.raise_()
        self._panel.activateWindow()

    def _on_activated(self, reason):
        if reason == QSystemTrayIcon.DoubleClick:
            self._show_panel()

    def _on_autostart_toggled(self, checked):
        self._settings.autostart = checked
        if checked:
            enable_autostart()
        else:
            disable_autostart()

    def _on_break_tick(self, remaining, total):
        """Update tooltip and menu text when break timer ticks."""
        self._update_break_text()
        # Update tooltip to show countdown
        if self._break_reminder.enabled and not self._break_reminder.is_on_break:
            minutes, seconds = divmod(remaining, 60)
            self.setToolTip(f"OpenCareEyes - 下次休息: {minutes}:{seconds:02d}")
        elif self._break_reminder.is_on_break:
            self.setToolTip("OpenCareEyes - 休息中")
        else:
            self.setToolTip("OpenCareEyes")