"""System tray controls backed by the same state as the main window."""

from __future__ import annotations

import os

from PySide6.QtCore import QSignalBlocker
from PySide6.QtGui import QAction, QActionGroup, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from opencareyes.application.status_presenter import StatusPresenter
from opencareyes.constants import ICONS_DIR
from opencareyes.ui.widgets import (
    first_state_value,
    format_duration,
    suppression_reason_description,
    temperature_description,
)


class TrayIcon(QSystemTrayIcon):
    """Quick actions that never write settings or services directly."""

    def __init__(
        self,
        controller,
        panel,
        pet_surface=None,
        parent=None,
        *,
        companion_runtime=None,
    ):
        super().__init__(parent)
        self._controller = controller
        self._panel = panel
        self._pet_surface = pet_surface
        self._mini_countdown = pet_surface
        self._companion_runtime = companion_runtime
        self._create_icon()
        self._create_menu()
        self.activated.connect(self._on_activated)
        self._controller.state_changed.connect(self.render)
        notification = getattr(self._controller, "notification_requested", None)
        if notification is not None:
            notification.connect(self._show_notification)
        failed = getattr(self._controller, "operation_failed", None)
        if failed is not None:
            failed.connect(self._show_error)
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
        self._pet_action = self._check_action("显示桌面伙伴", self._toggle_pet)
        self._rest_now_action = self._menu.addAction("现在休息")
        self._rest_now_action.triggered.connect(self._start_break_now)

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

        protection_menu = self._menu.addMenu("屏幕舒适与专注")
        self._filter_action = self._check_action(
            "色温调节", self.toggle_filter, protection_menu
        )
        self._dimmer_action = self._check_action(
            "屏幕调暗", self.toggle_dimmer, protection_menu
        )
        self._focus_action = self._check_action(
            "专注模式", self.toggle_focus, protection_menu
        )
        profile_menu = protection_menu.addMenu("显示方案")
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

        self._break_control_menu = self._menu.addMenu("休息提醒")
        self._break_action = self._check_action(
            "启用休息提醒", self.toggle_break, self._break_control_menu
        )
        self._pause_break_action = self._break_control_menu.addAction("暂停计时")
        self._pause_break_action.triggered.connect(self._toggle_break_pause)
        self._snooze_menu = self._break_control_menu.addMenu("稍后提醒")
        for minutes in (5, 10, 30):
            self._snooze_menu.addAction(f"{minutes} 分钟").triggered.connect(
                lambda checked=False, delay=minutes: self._controller.snooze_break(delay)
            )
        self._context_status_action = self._break_control_menu.addAction(
            "智能免打扰：未触发"
        )
        self._context_status_action.setEnabled(False)
        self._resume_context_action = self._break_control_menu.addAction(
            "本次场景继续提醒"
        )
        self._resume_context_action.triggered.connect(
            self._controller.resume_breaks_for_current_context
        )

        companion_menu = self._menu.addMenu("伙伴")
        self._open_pet_bubble_action = companion_menu.addAction("打开伙伴气泡")
        self._open_pet_bubble_action.triggered.connect(self._show_pet_bubble)
        self._preview_pet_action = companion_menu.addAction("预览桌面伙伴")
        self._preview_pet_action.triggered.connect(self._preview_pet)
        self._reset_pet_action = companion_menu.addAction("重置桌宠位置")
        self._reset_pet_action.triggered.connect(self._reset_pet_position)

        self._menu.addSeparator()
        settings_menu = self._menu.addMenu("设置与自动化")
        self._autostart_action = self._check_action(
            "开机自动启动", self._controller.set_autostart, settings_menu
        )
        settings_menu.addAction("自动日程…").triggered.connect(
            lambda: self._panel.show_page("自动日程")
        )
        settings_menu.addAction("设置…").triggered.connect(
            lambda: self._panel.show_page("设置")
        )
        self._menu.addSeparator()
        self._menu.addAction("退出 OpenCareEyes").triggered.connect(QApplication.quit)
        self._menu.aboutToShow.connect(lambda: self.render(self._controller.state))
        self.setContextMenu(self._menu)

    def _check_action(self, text: str, callback, menu=None) -> QAction:
        action = (menu or self._menu).addAction(text)
        action.setCheckable(True)
        action.triggered.connect(callback)
        return action

    def _start_break_now(self) -> None:
        starter = getattr(self._controller, "start_break_now", None)
        if callable(starter):
            starter()

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

    def _toggle_pet(self, visible: bool) -> None:
        setter = getattr(self._controller, "set_companion_enabled", None)
        if callable(setter):
            setter(bool(visible))

    def _preview_pet(self) -> None:
        preview = getattr(self._mini_countdown, "preview", None)
        if callable(preview):
            preview()

    def _show_pet_bubble(self) -> None:
        show_bubble = getattr(self._companion_runtime, "show_bubble", None)
        if callable(show_bubble):
            show_bubble(focusable=True)

    def _reset_pet_position(self) -> None:
        reset = getattr(self._mini_countdown, "reset_position", None)
        if callable(reset):
            reset()
            return
        command = getattr(self._controller, "reset_pet_position", None)
        if callable(command):
            command()

    def _toggle_break_pause(self) -> None:
        suppressed = tuple(first_state_value(
            self._controller.state,
            "effective_policy.breaks.suppressed_by",
            default=(),
        ))
        if suppressed:
            return
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

    def _show_error(self, _code: str, message: str) -> None:
        self.showMessage("OpenCareEyes 操作未完成", message, QSystemTrayIcon.Warning, 7000)

    def render(self, state) -> None:
        filter_enabled = bool(first_state_value(state, "display.filter_enabled", default=False))
        dimmer_enabled = bool(first_state_value(state, "display.dimmer_enabled", default=False))
        break_enabled = bool(first_state_value(state, "breaks.enabled", default=False))
        focus_enabled = bool(first_state_value(state, "focus.enabled", default=False))
        break_paused = bool(first_state_value(state, "breaks.paused", default=False))
        force_break = bool(first_state_value(state, "breaks.force_break", default=False))
        break_phase = str(first_state_value(state, "breaks.phase", default="stopped"))
        break_suppressed = tuple(first_state_value(
            state, "effective_policy.breaks.suppressed_by", default=()
        ))
        break_resume = str(first_state_value(
            state, "effective_policy.breaks.resume_condition", default=""
        ))
        countdown_display = str(first_state_value(
            state, "breaks.countdown_display", default="tray"
        ))
        companion_enabled = bool(first_state_value(
            state, "companion.enabled", default=True
        ))
        companion_visible = bool(first_state_value(
            state, "companion.visible", default=companion_enabled
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
        with QSignalBlocker(self._pet_action):
            self._pet_action.setChecked(companion_enabled)
        self._pet_action.setEnabled(True)
        self._pet_action.setToolTip("在桌面显示可拖动的陪伴宠物")
        pet_available = self._mini_countdown is not None
        self._open_pet_bubble_action.setEnabled(
            companion_visible and self._companion_runtime is not None
        )
        self._open_pet_bubble_action.setToolTip(
            "用键盘操作伙伴快捷气泡"
            if companion_visible
            else "伙伴当前隐藏，恢复显示后可打开气泡"
        )
        self._preview_pet_action.setEnabled(pet_available)
        self._reset_pet_action.setEnabled(pet_available)
        self._filter_action.setText(
            f"色温调节 · {temperature_description(temp)} {temp}K"
            if filter_enabled else "色温调节"
        )
        self._dimmer_action.setText(
            f"屏幕调暗 · {round(dim_level * 100 / 200)}%"
            if dimmer_enabled else "屏幕调暗"
        )
        if break_enabled and break_suppressed:
            break_text = "休息提醒 · 智能暂停"
        elif break_enabled and countdown_display == "hidden":
            break_text = "休息提醒 · 运行中"
        elif break_enabled and break_phase == "resting":
            break_text = f"休息中 · {format_duration(remaining)}"
        elif break_enabled:
            break_text = f"休息提醒 · {format_duration(remaining)}"
        else:
            break_text = "休息提醒"
        self._break_action.setText(break_text)
        self._pause_break_action.setText("继续计时" if break_paused else "暂停计时")
        self._pause_break_action.setEnabled(break_enabled and not break_suppressed)
        self._break_control_menu.setEnabled(True)
        self._rest_now_action.setEnabled(break_enabled and not break_suppressed)
        self._snooze_menu.setEnabled(
            break_enabled and not force_break and not break_suppressed
        )
        if break_suppressed:
            reason = "、".join(
                suppression_reason_description(item)
                for item in break_suppressed
            )
            detail = f" · {break_resume}" if break_resume else ""
            self._context_status_action.setText(f"智能免打扰：{reason}{detail}")
        else:
            self._context_status_action.setText("智能免打扰：未触发")
        self._resume_context_action.setVisible(
            bool(break_suppressed)
            and not {
                "locked",
                "session_locked",
                "suspended",
                "system_suspended",
            }.intersection(break_suppressed)
        )
        for name, action in self._profile_actions.items():
            with QSignalBlocker(action):
                action.setChecked(name == preset)

        autostart = bool(first_state_value(state, "general.autostart", default=False))
        with QSignalBlocker(self._autostart_action):
            self._autostart_action.setChecked(autostart)
        self._resume_all_action.setVisible(globally_paused)

        presentation = StatusPresenter.project(state)
        tooltip = (
            f"OpenCareEyes · {presentation.headline} · "
            f"{presentation.next_break_text}"
        )
        self.setToolTip(tooltip[:127])
