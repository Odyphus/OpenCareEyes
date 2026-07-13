"""Break rhythm page backed by the central break state machine."""

from __future__ import annotations

from PySide6.QtCore import QSignalBlocker
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSpinBox,
    QToolButton,
)

from opencareyes.ui.widgets import (
    Card,
    PageHeader,
    ScrollPage,
    first_state_value,
    format_duration,
    refresh_property,
    set_accessible,
)


BREAK_MODES = {
    "20-20-20": "20-20-20",
    "pomodoro": "番茄钟",
    "custom": "自定义",
}


class BreakPage(ScrollPage):
    """Configure and control the single authoritative break timer."""

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self._controller = controller
        self._rendering = False
        self._build_ui()
        self._connect_signals()
        self.render(controller.state)

    def _build_ui(self) -> None:
        self.layout.addWidget(PageHeader(
            "休息节奏",
            "到点后自动全屏置顶，帮助你停下工作。可暂停、稍后提醒，也始终可以安全结束。",
        ))

        status_card = Card()
        status_row = QHBoxLayout()
        status_text = QHBoxLayout()
        self._status_dot = QLabel()
        self._status_dot.setObjectName("statusDot")
        self._status_dot.setFixedSize(10, 10)
        self._status_label = QLabel("提醒未启用")
        self._status_label.setObjectName("sectionLead")
        status_text.addWidget(self._status_dot)
        status_text.addWidget(self._status_label)
        status_row.addLayout(status_text)
        status_row.addStretch()
        self._enable_toggle = QCheckBox("启用休息提醒")
        set_accessible(self._enable_toggle, "启用休息提醒")
        status_row.addWidget(self._enable_toggle)
        status_card.body.addLayout(status_row)

        action_row = QHBoxLayout()
        self._pause_button = QPushButton("暂停计时")
        self._pause_button.setObjectName("secondaryButton")
        set_accessible(self._pause_button, "暂停休息计时")
        self._snooze_button = QToolButton()
        self._snooze_button.setText("稍后提醒")
        self._snooze_button.setPopupMode(QToolButton.InstantPopup)
        snooze_menu = QMenu(self._snooze_button)
        for minutes in (5, 10, 30):
            action = snooze_menu.addAction(f"{minutes} 分钟后提醒")
            action.triggered.connect(
                lambda checked=False, delay=minutes: self._controller.snooze_break(delay)
            )
        self._snooze_button.setMenu(snooze_menu)
        set_accessible(self._snooze_button, "稍后提醒菜单")
        self._skip_button = QPushButton("结束本次休息")
        self._skip_button.setObjectName("quietButton")
        self._skip_button.clicked.connect(self._controller.skip_break)
        action_row.addWidget(self._pause_button)
        action_row.addWidget(self._snooze_button)
        action_row.addWidget(self._skip_button)
        action_row.addStretch()
        status_card.body.addLayout(action_row)
        self.layout.addWidget(status_card)

        rhythm_card = Card("提醒模式", "选择常用节奏，或使用自定义时长。")
        form = QFormLayout()
        form.setHorizontalSpacing(24)
        form.setVerticalSpacing(12)
        self._mode_combo = QComboBox()
        for key, label in BREAK_MODES.items():
            self._mode_combo.addItem(label, key)
        set_accessible(self._mode_combo, "休息提醒模式")
        form.addRow("模式", self._mode_combo)

        self._work_spin = QSpinBox()
        self._work_spin.setRange(1, 180)
        self._work_spin.setSuffix(" 分钟")
        set_accessible(self._work_spin, "连续用眼时长")
        form.addRow("连续用眼", self._work_spin)

        self._break_spin = QSpinBox()
        set_accessible(self._break_spin, "每次休息时长")
        form.addRow("每次休息", self._break_spin)
        rhythm_card.body.addLayout(form)
        self.layout.addWidget(rhythm_card)

        advanced_card = Card(
            "高级设置",
            "所有休息都会显示全屏提示。严格模式会隐藏“稍后提醒”，但仍可按 Esc 安全结束。",
        )
        self._force_toggle = QCheckBox("严格休息模式")
        set_accessible(
            self._force_toggle,
            "严格休息模式",
            "严格模式不允许延后，但始终保留安全退出途径",
        )
        advanced_form = QFormLayout()
        self._display_combo = QComboBox()
        self._display_combo.addItem("仅在托盘显示", "tray")
        self._display_combo.addItem("显示倒计时桌宠", "floating")
        self._display_combo.addItem("完全隐藏倒计时", "hidden")
        set_accessible(self._display_combo, "休息倒计时显示方式")
        advanced_form.addRow("倒计时显示", self._display_combo)
        advanced_form.addRow(self._force_toggle)
        advanced_card.body.addLayout(advanced_form)
        self.layout.addWidget(advanced_card)
        self.layout.addStretch()

    def _connect_signals(self) -> None:
        self._enable_toggle.toggled.connect(
            lambda enabled: self._controller.set_feature_enabled("breaks", enabled)
        )
        self._pause_button.clicked.connect(self._toggle_pause)
        self._mode_combo.currentIndexChanged.connect(self._mode_changed)
        self._work_spin.editingFinished.connect(self._durations_changed)
        self._break_spin.editingFinished.connect(self._durations_changed)
        self._force_toggle.toggled.connect(self._controller.set_force_break)
        self._display_combo.currentIndexChanged.connect(self._display_mode_changed)
        self._controller.state_changed.connect(self.render)

    def _toggle_pause(self) -> None:
        paused = bool(first_state_value(self._controller.state, "breaks.paused", default=False))
        if paused:
            self._controller.resume_break()
        else:
            self._controller.pause_break()

    def _mode_changed(self, index: int) -> None:
        if self._rendering:
            return
        mode = self._mode_combo.itemData(index)
        self._configure_break_spin(mode)
        self._controller.set_break_mode(mode)

    def _configure_break_spin(self, mode: str) -> None:
        with QSignalBlocker(self._break_spin):
            if mode == "20-20-20":
                self._break_spin.setRange(5, 120)
                self._break_spin.setSuffix(" 秒")
            else:
                self._break_spin.setRange(1, 60)
                self._break_spin.setSuffix(" 分钟")

    def _durations_changed(self) -> None:
        if self._rendering:
            return
        mode = self._mode_combo.currentData()
        work_seconds = self._work_spin.value() * 60
        break_seconds = self._break_spin.value()
        if mode != "20-20-20":
            break_seconds *= 60
        self._controller.set_break_durations(work_seconds, break_seconds)

    def _display_mode_changed(self, index: int) -> None:
        if self._rendering:
            return
        self._controller.set_break_countdown_display(
            self._display_combo.itemData(index)
        )

    def render(self, state) -> None:
        self._rendering = True
        try:
            enabled = bool(first_state_value(state, "breaks.enabled", default=False))
            phase = str(first_state_value(state, "breaks.phase", default="stopped"))
            paused = bool(first_state_value(state, "breaks.paused", default=False))
            remaining = first_state_value(state, "breaks.remaining", default=0)
            mode = str(first_state_value(state, "breaks.mode", default="20-20-20"))
            work_seconds = int(first_state_value(state, "breaks.work_duration", default=20 * 60))
            break_seconds = int(first_state_value(state, "breaks.break_duration", default=20))
            force = bool(first_state_value(state, "breaks.force_break", default=False))
            display_mode = str(first_state_value(
                state, "breaks.countdown_display", default="tray"
            ))
            available = bool(first_state_value(state, "capabilities.breaks_available", default=True))

            with QSignalBlocker(self._enable_toggle):
                self._enable_toggle.setChecked(enabled)
            index = self._mode_combo.findData(mode)
            if index >= 0:
                with QSignalBlocker(self._mode_combo):
                    self._mode_combo.setCurrentIndex(index)
            self._configure_break_spin(mode)
            with QSignalBlocker(self._work_spin):
                self._work_spin.setValue(max(1, work_seconds // 60))
            with QSignalBlocker(self._break_spin):
                value = break_seconds if mode == "20-20-20" else max(1, break_seconds // 60)
                self._break_spin.setValue(value)
            with QSignalBlocker(self._force_toggle):
                self._force_toggle.setChecked(force)
            display_index = self._display_combo.findData(display_mode)
            if display_index >= 0:
                with QSignalBlocker(self._display_combo):
                    self._display_combo.setCurrentIndex(display_index)

            if not enabled or phase == "stopped":
                status = "提醒未启用"
            elif paused:
                status = f"计时已暂停 · 剩余 {format_duration(remaining)}"
            elif phase == "resting":
                status = f"休息中 · 剩余 {format_duration(remaining)}"
            else:
                status = f"距离下次休息 {format_duration(remaining)}"
            self._status_label.setText(status)
            self._status_label.setAccessibleName(status)
            refresh_property(self._status_dot, "active", enabled and not paused)

            self._pause_button.setText("继续计时" if paused else "暂停计时")
            self._pause_button.setEnabled(enabled)
            self._snooze_button.setEnabled(enabled and not force)
            self._skip_button.setVisible(enabled and phase == "resting")
            for widget in (
                self._enable_toggle,
                self._mode_combo,
                self._work_spin,
                self._break_spin,
                self._force_toggle,
                self._display_combo,
            ):
                widget.setEnabled(available)
        finally:
            self._rendering = False
