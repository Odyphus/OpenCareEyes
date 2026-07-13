"""General, hotkey, privacy, and diagnostics settings."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSignalBlocker, QStandardPaths
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
)

from opencareyes.constants import APP_NAME, APP_VERSION
from opencareyes.ui.widgets import Card, PageHeader, ScrollPage, first_state_value, set_accessible


_HOTKEY_FIELDS = (
    ("filter", "色温调节"),
    ("dimmer", "屏幕调暗"),
    ("breaks", "休息提醒"),
    ("focus", "专注模式"),
)


class SettingsPage(ScrollPage):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self._controller = controller
        self._rendering = False
        self._build_ui()
        self._connect_signals()
        self.render(controller.state)

    def _build_ui(self) -> None:
        self.layout.addWidget(PageHeader(
            "设置",
            "管理外观、开机启动、快捷键与本地数据。所有核心功能均可离线使用。",
        ))

        general_card = Card("常规")
        general_form = QFormLayout()
        general_form.setHorizontalSpacing(24)
        general_form.setVerticalSpacing(12)
        self._theme_combo = QComboBox()
        self._theme_combo.addItem("跟随系统", "system")
        self._theme_combo.addItem("亮色", "light")
        self._theme_combo.addItem("暗色", "dark")
        set_accessible(self._theme_combo, "应用主题")
        general_form.addRow("主题", self._theme_combo)
        self._motion_combo = QComboBox()
        self._motion_combo.addItem("跟随系统", "system")
        self._motion_combo.addItem("标准动画", "standard")
        self._motion_combo.addItem("减少动画", "reduced")
        set_accessible(self._motion_combo, "动画效果")
        general_form.addRow("动画效果", self._motion_combo)
        self._autostart_toggle = QCheckBox("登录 Windows 后自动启动")
        set_accessible(self._autostart_toggle, "开机自动启动")
        general_form.addRow("开机启动", self._autostart_toggle)
        general_card.body.addLayout(general_form)
        self.layout.addWidget(general_card)

        hotkey_card = Card("快捷键", "点击输入框后按下组合键。保存时会检查冲突。")
        hotkey_form = QFormLayout()
        hotkey_form.setHorizontalSpacing(24)
        hotkey_form.setVerticalSpacing(10)
        self._hotkey_edits: dict[str, QLineEdit] = {}
        for key, label in _HOTKEY_FIELDS:
            edit = QLineEdit()
            edit.setPlaceholderText("例如 Ctrl+Alt+N")
            edit.setClearButtonEnabled(True)
            set_accessible(edit, f"{label}快捷键")
            hotkey_form.addRow(label, edit)
            self._hotkey_edits[key] = edit
        hotkey_card.body.addLayout(hotkey_form)
        hotkey_actions = QHBoxLayout()
        self._reset_hotkeys_button = QPushButton("恢复默认")
        self._reset_hotkeys_button.setObjectName("quietButton")
        self._save_hotkeys_button = QPushButton("保存快捷键")
        self._save_hotkeys_button.setObjectName("primaryButton")
        set_accessible(self._reset_hotkeys_button, "恢复默认快捷键")
        set_accessible(self._save_hotkeys_button, "保存快捷键")
        hotkey_actions.addStretch()
        hotkey_actions.addWidget(self._reset_hotkeys_button)
        hotkey_actions.addWidget(self._save_hotkeys_button)
        hotkey_card.body.addLayout(hotkey_actions)
        self.layout.addWidget(hotkey_card)

        data_card = Card(
            "隐私与诊断",
            "无账号、无遥测。诊断文件不包含窗口标题、位置坐标或其他个人内容。",
        )
        data_actions = QHBoxLayout()
        self._export_button = QPushButton("导出诊断信息")
        self._export_button.setObjectName("secondaryButton")
        self._reset_button = QPushButton("清除本地设置")
        self._reset_button.setObjectName("dangerButton")
        set_accessible(self._export_button, "导出诊断信息")
        set_accessible(self._reset_button, "清除全部本地设置")
        data_actions.addWidget(self._export_button)
        data_actions.addWidget(self._reset_button)
        data_actions.addStretch()
        data_card.body.addLayout(data_actions)
        self.layout.addWidget(data_card)

        about_card = Card("关于")
        app_label = QLabel(f"{APP_NAME}  v{APP_VERSION}")
        app_label.setObjectName("sectionLead")
        description = QLabel(
            "本地优先、低打扰的 Windows 护眼助手。\n"
            "Apache-2.0 开源许可 · 核心功能完全离线"
        )
        description.setObjectName("cardDescription")
        description.setWordWrap(True)
        about_card.body.addWidget(app_label)
        about_card.body.addWidget(description)
        self.layout.addWidget(about_card)
        self.layout.addStretch()

    def _connect_signals(self) -> None:
        self._theme_combo.currentIndexChanged.connect(self._theme_changed)
        self._motion_combo.currentIndexChanged.connect(self._motion_changed)
        self._autostart_toggle.toggled.connect(self._autostart_changed)
        self._save_hotkeys_button.clicked.connect(self._save_hotkeys)
        self._reset_hotkeys_button.clicked.connect(self._controller.reset_hotkeys)
        self._export_button.clicked.connect(self._export_diagnostics)
        self._reset_button.clicked.connect(self._reset_settings)
        self._controller.state_changed.connect(self.render)

    def _theme_changed(self, index: int) -> None:
        if not self._rendering:
            self._controller.set_theme(self._theme_combo.itemData(index))

    def _motion_changed(self, index: int) -> None:
        if not self._rendering:
            self._controller.set_motion_mode(self._motion_combo.itemData(index))

    def _autostart_changed(self, enabled: bool) -> None:
        if not self._rendering:
            self._controller.set_autostart(enabled)

    def _save_hotkeys(self) -> None:
        values = [edit.text().strip() for edit in self._hotkey_edits.values()]
        normalized = [value.lower() for value in values if value]
        duplicates = {value for value in normalized if normalized.count(value) > 1}
        if duplicates:
            QMessageBox.warning(self, "快捷键冲突", "同一个组合键不能分配给多个功能。")
            return
        for action, edit in self._hotkey_edits.items():
            self._controller.set_hotkey(action, edit.text().strip())

    def _export_diagnostics(self) -> None:
        exporter = getattr(self._controller, "export_diagnostics", None)
        if not callable(exporter):
            return
        documents = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation)
        suggested = str(Path(documents) / "OpenCareEyes-diagnostics.zip")
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出诊断信息",
            suggested,
            "ZIP 压缩包 (*.zip)",
        )
        if path:
            exporter(path)

    def _reset_settings(self) -> None:
        resetter = getattr(self._controller, "reset_settings", None)
        if not callable(resetter):
            return
        answer = QMessageBox.question(
            self,
            "清除本地设置？",
            "这会恢复所有显示、休息、自动化和快捷键设置。此操作无法撤销。",
            QMessageBox.Reset | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if answer == QMessageBox.Reset:
            resetter()

    def render(self, state) -> None:
        self._rendering = True
        try:
            theme = str(first_state_value(state, "general.theme", default="system"))
            autostart = bool(first_state_value(state, "general.autostart", default=False))
            index = self._theme_combo.findData(theme)
            if index >= 0:
                with QSignalBlocker(self._theme_combo):
                    self._theme_combo.setCurrentIndex(index)
            motion_mode = str(first_state_value(
                state, "general.motion_mode", default="system"
            ))
            motion_index = self._motion_combo.findData(motion_mode)
            if motion_index >= 0:
                with QSignalBlocker(self._motion_combo):
                    self._motion_combo.setCurrentIndex(motion_index)
            with QSignalBlocker(self._autostart_toggle):
                self._autostart_toggle.setChecked(autostart)
            for action, edit in self._hotkey_edits.items():
                value = str(first_state_value(
                    state,
                    f"general.hotkeys.{action}",
                    f"hotkeys.{action}",
                    default="",
                ))
                if not edit.hasFocus():
                    with QSignalBlocker(edit):
                        edit.setText(value)
            hotkeys_available = bool(first_state_value(
                state, "capabilities.hotkeys_available", default=True
            ))
            self._save_hotkeys_button.setEnabled(hotkeys_available)
            for edit in self._hotkey_edits.values():
                edit.setEnabled(hotkeys_available)
            exporter_available = callable(getattr(self._controller, "export_diagnostics", None))
            self._export_button.setEnabled(exporter_available)
            if not exporter_available:
                self._export_button.setToolTip("当前运行环境不支持导出诊断信息")
            reset_available = callable(getattr(self._controller, "reset_settings", None))
            self._reset_button.setEnabled(reset_available)
        finally:
            self._rendering = False
