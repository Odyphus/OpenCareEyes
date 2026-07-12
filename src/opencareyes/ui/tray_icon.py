"""System tray controls backed by the same state as the main window."""

from __future__ import annotations

import os

from PySide6.QtCore import QSignalBlocker
from PySide6.QtGui import QAction, QActionGroup, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from opencareyes.constants import ICONS_DIR
from opencareyes.ui.widgets import first_state_value, format_duration, temperature_description


class TrayIcon(QSystemTrayIcon):
    """Quick actions that never write settings or services directly."""

    def __init__(self, controller, panel, mini_countdown=None, parent=None):
        super().__init__(parent)
        self._controller = controller
        self._panel = panel
        self._mini_countdown = mini_countdown
        self._create_icon()
        self._create_menu()
        self.activated.connect(self._on_activated)
        self._controller.state_changed.connect(self.render)
        notification = getattr(self._controller, "notification_requested", None)
        if notification is not None:
            notification.connect(self._show_notification)
        self.render(controller.state)

    def _create_icon(self) -> None:
        for name in ("tray_light.png", "tray_dark.png"):
            path = os.path.join(ICONS_DIR, name)
            if os.path.isfile(path):
                self.setIcon(QIcon(path))
                return
        pixmap = QPixmap(32, 32)
        pixmap.fill(QColor(0, 0, 0, 0))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QColor("#5B8DEF"))
        painter.setPen(QColor("#FFFFFF"))
        painter.drawEllipse(2, 2, 28, 28)
        painter.drawEllipse(9, 11, 5, 5)
        painter.drawEllipse(18, 11, 5, 5)
        painter.end()
        self.setIcon(QIcon(pixmap))

    def _create_menu(self) -> None:
        self._menu = QMenu()
        self._open_action = self._menu.addAction("打开 OpenCareEyes")
        self._open_action.triggered.connect(self._show_panel)
        self._menu.addSeparator()

        self._filter_action = self._check_action("色温调节", self.toggle_filter)
        self._dimmer_action = self._check_action("屏幕调暗", self.toggle_dimmer)
        self._break_action = self._check_action("休息提醒", self.toggle_break)
        self._focus_action = self._check_action("专注模式", self.toggle_focus)

        self._break_control_menu = self._menu.addMenu("休息计时")
        self._pause_break_action = self._break_control_menu.addAction("暂停计时")
        self._pause_break_action.triggered.connect(self._toggle_break_pause)
        self._snooze_menu = self._break_control_menu.addMenu("稍后提醒")
        for minutes in (5, 10, 30):
            self._snooze_menu.addAction(f"{minutes} 分钟").triggered.connect(
                lambda checked=False, delay=minutes: self._controller.snooze_break(delay)
            )

        profile_menu = self._menu.addMenu("显示方案")
        self._profile_group = QActionGroup(self)
        self._profile_group.setExclusive(True)
        self._profile_actions: dict[str, QAction] = {}
        for key, label in (
            ("office", "办公"),
            ("reading", "阅读"),
            ("night", "夜间"),
            ("game", "游戏"),
        ):
            action = profile_menu.addAction(label)
            action.setCheckable(True)
            action.triggered.connect(
                lambda checked=False, profile=key: self.apply_preset(profile)
            )
            self._profile_group.addAction(action)
            self._profile_actions[key] = action

        pause_menu = self._menu.addMenu("暂停全部")
        pause_menu.addAction("30 分钟").triggered.connect(
            lambda: self._controller.pause_all(minutes=30)
        )
        pause_menu.addAction("1 小时").triggered.connect(
            lambda: self._controller.pause_all(minutes=60)
        )
        pause_menu.addAction("直到下一次自动切换").triggered.connect(
            lambda: self._controller.pause_all(minutes=None, until_next_schedule=True)
        )
        pause_menu.addAction("直到手动恢复").triggered.connect(
            lambda: self._controller.pause_all(minutes=None)
        )
        self._resume_all_action = self._menu.addAction("恢复全部效果")
        self._resume_all_action.triggered.connect(self._controller.resume_all)

        self._menu.addSeparator()
        self._autostart_action = self._check_action(
            "开机自动启动", self._controller.set_autostart
        )
        self._menu.addAction("自动化设置…").triggered.connect(
            lambda: self._panel.show_page("自动化")
        )
        self._menu.addAction("设置…").triggered.connect(
            lambda: self._panel.show_page("设置")
        )
        self._menu.addSeparator()
        self._menu.addAction("退出 OpenCareEyes").triggered.connect(QApplication.quit)
        self._menu.aboutToShow.connect(lambda: self.render(self._controller.state))
        self.setContextMenu(self._menu)

    def _check_action(self, text: str, callback) -> QAction:
        action = self._menu.addAction(text)
        action.setCheckable(True)
        action.triggered.connect(callback)
        return action

    def toggle_filter(self, checked: bool | None = None) -> None:
        enabled = bool(first_state_value(
            self._controller.state, "display.filter_enabled", default=False
        ))
        self._controller.set_feature_enabled("filter", not enabled if checked is None else checked)

    def toggle_dimmer(self, checked: bool | None = None) -> None:
        enabled = bool(first_state_value(
            self._controller.state, "display.dimmer_enabled", default=False
        ))
        self._controller.set_feature_enabled("dimmer", not enabled if checked is None else checked)

    def toggle_break(self, checked: bool | None = None) -> None:
        enabled = bool(first_state_value(self._controller.state, "breaks.enabled", default=False))
        self._controller.set_feature_enabled("breaks", not enabled if checked is None else checked)

    def toggle_focus(self, checked: bool | None = None) -> None:
        enabled = bool(first_state_value(self._controller.state, "focus.enabled", default=False))
        self._controller.set_feature_enabled("focus", not enabled if checked is None else checked)

    def apply_preset(self, name: str) -> None:
        self._controller.apply_display_profile(name)

    def _toggle_break_pause(self) -> None:
        paused = bool(first_state_value(self._controller.state, "breaks.paused", default=False))
        if paused:
            self._controller.resume_break()
        else:
            self._controller.pause_break()

    def _show_panel(self) -> None:
        if hasattr(self._panel, "show_and_activate"):
            self._panel.show_and_activate()
        else:
            self._panel.show()
            self._panel.raise_()
            self._panel.activateWindow()

    def _on_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.Trigger:
            if hasattr(self._panel, "toggle_visible"):
                self._panel.toggle_visible()
            else:
                self._show_panel()
        elif reason == QSystemTrayIcon.DoubleClick:
            self._show_panel()

    def _show_notification(self, title: str, message: str) -> None:
        self.showMessage(title, message, QSystemTrayIcon.Information, 5000)

    def render(self, state) -> None:
        filter_enabled = bool(first_state_value(state, "display.filter_enabled", default=False))
        dimmer_enabled = bool(first_state_value(state, "display.dimmer_enabled", default=False))
        break_enabled = bool(first_state_value(state, "breaks.enabled", default=False))
        focus_enabled = bool(first_state_value(state, "focus.enabled", default=False))
        break_paused = bool(first_state_value(state, "breaks.paused", default=False))
        force_break = bool(first_state_value(state, "breaks.force_break", default=False))
        break_phase = str(first_state_value(state, "breaks.phase", default="stopped"))
        countdown_display = str(first_state_value(
            state, "breaks.countdown_display", default="tray"
        ))
        remaining = first_state_value(state, "breaks.remaining", default=0)
        temp = int(first_state_value(state, "display.color_temperature", default=6500))
        dim_level = int(first_state_value(state, "display.dim_level", default=0))
        preset = str(first_state_value(state, "display.preset", default="custom"))
        globally_paused = bool(first_state_value(state, "global_pause.active", default=False))

        for action, checked in (
            (self._filter_action, filter_enabled),
            (self._dimmer_action, dimmer_enabled),
            (self._break_action, break_enabled),
            (self._focus_action, focus_enabled),
        ):
            with QSignalBlocker(action):
                action.setChecked(checked)
        self._filter_action.setText(
            f"色温调节 · {temperature_description(temp)} {temp}K"
            if filter_enabled else "色温调节"
        )
        self._dimmer_action.setText(
            f"屏幕调暗 · {round(dim_level * 100 / 200)}%"
            if dimmer_enabled else "屏幕调暗"
        )
        if break_enabled and countdown_display == "hidden":
            break_text = "休息提醒 · 运行中"
        elif break_enabled and break_phase == "resting":
            break_text = f"休息中 · {format_duration(remaining)}"
        elif break_enabled:
            break_text = f"休息提醒 · {format_duration(remaining)}"
        else:
            break_text = "休息提醒"
        self._break_action.setText(break_text)
        self._pause_break_action.setText("继续计时" if break_paused else "暂停计时")
        self._break_control_menu.setEnabled(break_enabled)
        self._snooze_menu.setEnabled(break_enabled and not force_break)
        for name, action in self._profile_actions.items():
            with QSignalBlocker(action):
                action.setChecked(name == preset)

        autostart = bool(first_state_value(state, "general.autostart", default=False))
        with QSignalBlocker(self._autostart_action):
            self._autostart_action.setChecked(autostart)
        self._resume_all_action.setVisible(globally_paused)

        if globally_paused:
            tooltip = "OpenCareEyes · 全部效果已暂停"
        elif break_enabled and countdown_display == "hidden":
            tooltip = "OpenCareEyes · 休息提醒运行中"
        elif break_enabled and break_phase == "resting":
            tooltip = f"OpenCareEyes · 正在休息 {format_duration(remaining)}"
        elif break_enabled:
            tooltip = f"OpenCareEyes · 下次休息 {format_duration(remaining)}"
        else:
            tooltip = "OpenCareEyes · 让屏幕更舒适"
        self.setToolTip(tooltip)
