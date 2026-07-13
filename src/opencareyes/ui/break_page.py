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
    "balanced": "平衡节奏",
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
            "按活跃用眼时间安排短休息与长休息；温和提醒不会突然打断当前操作。",
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
        self._cadence_label = QLabel("短休息与长休息将在这里显示")
        self._cadence_label.setObjectName("mutedText")
        self._cadence_label.setWordWrap(True)
        status_card.body.addWidget(self._cadence_label)

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

        rhythm_card = Card("活动加权节奏", "只累计未暂停、未被情境抑制的活跃时间。")
        form = QFormLayout()
        form.setHorizontalSpacing(24)
        form.setVerticalSpacing(12)
        self._mode_combo = QComboBox()
        for key, label in BREAK_MODES.items():
            self._mode_combo.addItem(label, key)
        set_accessible(self._mode_combo, "休息节奏模式")
        form.addRow("模式", self._mode_combo)

        self._work_spin = QSpinBox()
        self._work_spin.setRange(1, 180)
        self._work_spin.setSuffix(" 分钟")
        set_accessible(self._work_spin, "短休息间隔")
        form.addRow("短休息间隔", self._work_spin)

        self._break_spin = QSpinBox()
        self._break_spin.setRange(5, 3600)
        self._break_spin.setSuffix(" 秒")
        set_accessible(self._break_spin, "短休息时长")
        form.addRow("短休息时长", self._break_spin)

        self._long_toggle = QCheckBox("启用长休息")
        set_accessible(self._long_toggle, "启用周期性长休息")
        form.addRow(self._long_toggle)
        self._long_interval_spin = QSpinBox()
        self._long_interval_spin.setRange(2, 360)
        self._long_interval_spin.setSuffix(" 分钟")
        set_accessible(self._long_interval_spin, "长休息间隔")
        form.addRow("长休息间隔", self._long_interval_spin)
        self._long_duration_spin = QSpinBox()
        self._long_duration_spin.setRange(1, 60)
        self._long_duration_spin.setSuffix(" 分钟")
        set_accessible(self._long_duration_spin, "长休息时长")
        form.addRow("长休息时长", self._long_duration_spin)
        rhythm_card.body.addLayout(form)
        self.layout.addWidget(rhythm_card)

        reminder_card = Card(
            "提醒方式",
            "温和渐进先显示可操作卡片；选择“现在休息”后才开始倒计时。",
        )
        reminder_form = QFormLayout()
        self._reminder_style_combo = QComboBox()
        self._reminder_style_combo.addItem("温和渐进提醒", "progressive")
        self._reminder_style_combo.addItem("到点立即全屏", "fullscreen")
        set_accessible(self._reminder_style_combo, "休息提醒显示方式")
        reminder_form.addRow("到点后", self._reminder_style_combo)
        reminder_card.body.addLayout(reminder_form)
        self.layout.addWidget(reminder_card)

        pet_card = Card(
            "倒计时桌宠",
            "作为功能型小伙伴显示状态；到点后可直接休息、延后或跳过。",
        )
        pet_form = QFormLayout()
        self._display_combo = QComboBox()
        self._display_combo.addItem("显示倒计时桌宠", "floating")
        self._display_combo.addItem("仅在托盘显示", "tray")
        self._display_combo.addItem("完全隐藏倒计时", "hidden")
        set_accessible(self._display_combo, "休息倒计时显示方式")
        pet_form.addRow("显示方式", self._display_combo)
        pet_actions = QHBoxLayout()
        self._pet_preview_button = QPushButton("显示桌宠")
        self._pet_preview_button.setObjectName("secondaryButton")
        self._pet_reset_button = QPushButton("重置位置")
        self._pet_reset_button.setObjectName("quietButton")
        pet_actions.addWidget(self._pet_preview_button)
        pet_actions.addWidget(self._pet_reset_button)
        pet_actions.addStretch()
        pet_card.body.addLayout(pet_form)
        pet_card.body.addLayout(pet_actions)
        self.layout.addWidget(pet_card)

        advanced_card = Card(
            "高级设置",
            "严格模式会立即全屏并隐藏“稍后提醒”，但仍保留明确的安全退出。",
        )
        self._force_toggle = QCheckBox("严格休息模式")
        set_accessible(
            self._force_toggle,
            "严格休息模式",
            "严格模式不允许延后，但始终保留安全退出途径",
        )
        advanced_form = QFormLayout()
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
        self._long_toggle.toggled.connect(self._durations_changed)
        self._long_interval_spin.editingFinished.connect(self._durations_changed)
        self._long_duration_spin.editingFinished.connect(self._durations_changed)
        self._force_toggle.toggled.connect(self._controller.set_force_break)
        self._reminder_style_combo.currentIndexChanged.connect(
            self._reminder_style_changed
        )
        self._display_combo.currentIndexChanged.connect(self._display_mode_changed)
        self._pet_preview_button.clicked.connect(
            lambda: self._controller.set_break_countdown_display("floating")
        )
        self._pet_reset_button.clicked.connect(self._reset_pet_position)
        self._controller.state_changed.connect(self.render)
        break_tick = getattr(self._controller, "break_tick", None)
        if break_tick is not None:
            break_tick.connect(self._render_break_tick)

    def _render_break_tick(self, *_args) -> None:
        self.render(self._controller.state)

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
        self._controller.set_break_mode(mode)

    def _configure_cadence_inputs(
        self, mode: str, long_enabled: bool, available: bool
    ) -> None:
        custom = mode == "custom" and available
        self._work_spin.setEnabled(custom)
        self._break_spin.setEnabled(custom)
        self._long_toggle.setEnabled(custom)
        self._long_interval_spin.setEnabled(custom and long_enabled)
        self._long_duration_spin.setEnabled(custom and long_enabled)

    def _durations_changed(self, *_args) -> None:
        if self._rendering:
            return
        mode = self._mode_combo.currentData()
        if mode != "custom":
            return
        short_interval = self._work_spin.value() * 60
        short_duration = self._break_spin.value()
        long_enabled = self._long_toggle.isChecked()
        self._long_interval_spin.setMinimum(self._work_spin.value() + 1)
        long_interval = self._long_interval_spin.value() * 60
        long_duration = self._long_duration_spin.value() * 60
        command = getattr(self._controller, "set_break_cadence", None)
        if command is not None:
            command(
                short_interval,
                short_duration,
                long_enabled,
                long_interval,
                long_duration,
            )
        else:
            self._controller.set_break_durations(short_interval, short_duration)

    def _reminder_style_changed(self, index: int) -> None:
        if self._rendering:
            return
        command = getattr(self._controller, "set_break_reminder_style", None)
        if command is not None:
            command(self._reminder_style_combo.itemData(index))

    def _reset_pet_position(self) -> None:
        command = getattr(self._controller, "reset_pet_position", None)
        if command is not None:
            command()

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
            remaining = int(first_state_value(state, "breaks.remaining", default=0))
            mode = str(first_state_value(
                state,
                "break_cadence.mode",
                "breaks.cadence.mode",
                "breaks.mode",
                default="20-20-20",
            ))
            short_interval = int(first_state_value(
                state,
                "break_cadence.short_interval",
                "breaks.cadence.short_interval",
                "breaks.short_interval",
                "breaks.work_duration",
                default=20 * 60,
            ))
            short_duration = int(first_state_value(
                state,
                "break_cadence.short_duration",
                "breaks.cadence.short_duration",
                "breaks.short_duration",
                "breaks.break_duration",
                default=20,
            ))
            long_enabled = bool(first_state_value(
                state,
                "break_cadence.long_enabled",
                "breaks.cadence.long_enabled",
                "breaks.long_enabled",
                default=False,
            ))
            long_interval = int(first_state_value(
                state,
                "break_cadence.long_interval",
                "breaks.cadence.long_interval",
                "breaks.long_interval",
                default=60 * 60,
            ))
            long_duration = int(first_state_value(
                state,
                "break_cadence.long_duration",
                "breaks.cadence.long_duration",
                "breaks.long_duration",
                default=5 * 60,
            ))
            short_remaining = int(first_state_value(
                state,
                "break_cadence.short_remaining",
                "breaks.cadence.short_remaining",
                "breaks.short_remaining",
                default=remaining,
            ))
            long_remaining = int(first_state_value(
                state,
                "break_cadence.long_remaining",
                "breaks.cadence.long_remaining",
                "breaks.long_remaining",
                default=long_interval if long_enabled else 0,
            ))
            force = bool(first_state_value(state, "breaks.force_break", default=False))
            reminder_style = str(first_state_value(
                state, "breaks.reminder_style", default="fullscreen"
            ))
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
            with QSignalBlocker(self._work_spin):
                self._work_spin.setValue(max(1, short_interval // 60))
            with QSignalBlocker(self._break_spin):
                self._break_spin.setValue(max(5, short_duration))
            with QSignalBlocker(self._long_toggle):
                self._long_toggle.setChecked(long_enabled)
            self._long_interval_spin.setMinimum(max(2, short_interval // 60 + 1))
            with QSignalBlocker(self._long_interval_spin):
                self._long_interval_spin.setValue(max(2, long_interval // 60))
            with QSignalBlocker(self._long_duration_spin):
                self._long_duration_spin.setValue(max(1, long_duration // 60))
            with QSignalBlocker(self._force_toggle):
                self._force_toggle.setChecked(force)
            style_index = self._reminder_style_combo.findData(reminder_style)
            if style_index >= 0:
                with QSignalBlocker(self._reminder_style_combo):
                    self._reminder_style_combo.setCurrentIndex(style_index)
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
            elif phase == "prompting":
                status = "休息提醒等待处理"
            elif phase == "snoozed":
                status = f"已延后 · {format_duration(remaining)} 后再次提醒"
            else:
                status = f"距离下次休息 {format_duration(remaining)}"
            self._status_label.setText(status)
            self._status_label.setAccessibleName(status)
            refresh_property(self._status_dot, "active", enabled and not paused)
            cadence_text = f"短休息还剩 {format_duration(short_remaining)}"
            if long_enabled:
                cadence_text += f" · 长休息还剩 {format_duration(long_remaining)}"
            self._cadence_label.setText(cadence_text)
            self._cadence_label.setAccessibleName(cadence_text)

            self._pause_button.setText("继续计时" if paused else "暂停计时")
            self._pause_button.setEnabled(enabled)
            due_surface = phase in {"resting", "prompting", "snoozed"}
            self._snooze_button.setEnabled(enabled and due_surface and not force)
            self._skip_button.setVisible(enabled and due_surface)
            for widget in (
                self._enable_toggle,
                self._mode_combo,
                self._force_toggle,
                self._reminder_style_combo,
                self._display_combo,
                self._pet_preview_button,
                self._pet_reset_button,
            ):
                widget.setEnabled(available)
            self._configure_cadence_inputs(mode, long_enabled, available)
        finally:
            self._rendering = False
