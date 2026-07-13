"""Automation page for fixed-time and sunrise/sunset display schedules."""

from __future__ import annotations

import inspect
import ntpath
from datetime import datetime

from PySide6.QtCore import QSignalBlocker, QTime
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTimeEdit,
    QWidget,
)

from opencareyes.config.presets import PRESETS
from opencareyes.ui.widgets import (
    Card,
    PageHeader,
    ScrollPage,
    feature_description,
    first_state_value,
    schedule_event_description,
    set_accessible,
    suppression_reason_description,
)


_CITIES = (
    ("选择城市…", None),
    ("北京", (39.9042, 116.4074)),
    ("上海", (31.2304, 121.4737)),
    ("广州", (23.1291, 113.2644)),
    ("深圳", (22.5431, 114.0579)),
    ("成都", (30.5728, 104.0668)),
    ("自定义坐标", "custom"),
)

_PROFILE_LABELS = {
    "office": "办公",
    "reading": "阅读",
    "night": "夜间",
    "game": "游戏",
    "movie": "电影",
    "custom": "自定义",
}


def _basename_app_id(path: object) -> str:
    value = ntpath.basename(str(path).strip()).lower()
    if not value.endswith(".exe") or len(value) > 128:
        return ""
    return value


class AutomationPage(ScrollPage):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self._controller = controller
        self._rendering = False
        self._last_state = controller.state
        self._rules_signature = None
        self._build_ui()
        self._connect_signals()
        self.render(controller.state)

    def _build_ui(self) -> None:
        self.layout.addWidget(PageHeader(
            "自动化",
            "按固定时间或当地日出日落切换显示效果。手动调整会保持到下一次自动切换。",
        ))

        status_card = Card("下一次动作")
        status_row = QHBoxLayout()
        self._next_event = QLabel("尚未启用自动化")
        self._next_event.setObjectName("statusValue")
        self._next_event.setWordWrap(True)
        self._schedule_toggle = QCheckBox("启用自动化")
        set_accessible(self._schedule_toggle, "启用自动化")
        status_row.addWidget(self._next_event, 1)
        status_row.addWidget(self._schedule_toggle)
        status_card.body.addLayout(status_row)
        self._override_label = QLabel("手动覆盖将持续到下一调度边界")
        self._override_label.setObjectName("warningLabel")
        self._override_label.setWordWrap(True)
        status_card.body.addWidget(self._override_label)
        self.layout.addWidget(status_card)

        rule_card = Card("切换规则")
        form = QFormLayout()
        form.setHorizontalSpacing(24)
        form.setVerticalSpacing(12)
        self._mode_combo = QComboBox()
        self._mode_combo.addItem("日出与日落", "sun")
        self._mode_combo.addItem("固定时间", "fixed")
        set_accessible(self._mode_combo, "自动化切换规则")
        form.addRow("规则", self._mode_combo)
        self._day_profile_combo = QComboBox()
        self._night_profile_combo = QComboBox()
        for profile in PRESETS:
            label = _PROFILE_LABELS.get(profile, profile)
            self._day_profile_combo.addItem(label, profile)
            self._night_profile_combo.addItem(label, profile)
        set_accessible(self._day_profile_combo, "自动化日间显示方案")
        set_accessible(self._night_profile_combo, "自动化夜间显示方案")
        form.addRow("日间方案", self._day_profile_combo)
        form.addRow("夜间方案", self._night_profile_combo)

        weekday_row = QHBoxLayout()
        self._weekday_buttons: list[QPushButton] = []
        for label in ("一", "二", "三", "四", "五", "六", "日"):
            button = QPushButton(label)
            button.setObjectName("dayButton")
            button.setCheckable(True)
            button.setChecked(label not in ("六", "日"))
            button.setFixedWidth(38)
            set_accessible(button, f"星期{label}")
            weekday_row.addWidget(button)
            self._weekday_buttons.append(button)
        form.addRow("生效日期", weekday_row)
        rule_card.body.addLayout(form)

        self._fixed_widget = QWidget()
        fixed_form = QFormLayout(self._fixed_widget)
        fixed_form.setContentsMargins(0, 4, 0, 0)
        self._on_time = QTimeEdit(QTime(19, 0))
        self._on_time.setDisplayFormat("HH:mm")
        self._off_time = QTimeEdit(QTime(7, 30))
        self._off_time.setDisplayFormat("HH:mm")
        set_accessible(self._on_time, "夜间方案开始时间")
        set_accessible(self._off_time, "夜间方案结束时间")
        fixed_form.addRow("切换到夜间", self._on_time)
        fixed_form.addRow("恢复日间", self._off_time)
        rule_card.body.addWidget(self._fixed_widget)

        self._location_widget = QWidget()
        location_form = QFormLayout(self._location_widget)
        location_form.setContentsMargins(0, 4, 0, 0)
        self._city_combo = QComboBox()
        for label, coordinates in _CITIES:
            self._city_combo.addItem(label, coordinates)
        set_accessible(self._city_combo, "用于日出日落计算的城市")
        location_form.addRow("城市", self._city_combo)
        self._latitude = QDoubleSpinBox()
        self._latitude.setRange(-90.0, 90.0)
        self._latitude.setDecimals(4)
        self._longitude = QDoubleSpinBox()
        self._longitude.setRange(-180.0, 180.0)
        self._longitude.setDecimals(4)
        set_accessible(self._latitude, "纬度")
        set_accessible(self._longitude, "经度")
        location_form.addRow("纬度", self._latitude)
        location_form.addRow("经度", self._longitude)
        self._sunrise_offset = QSpinBox()
        self._sunrise_offset.setRange(-120, 120)
        self._sunrise_offset.setSuffix(" 分钟")
        self._sunset_offset = QSpinBox()
        self._sunset_offset.setRange(-120, 120)
        self._sunset_offset.setSuffix(" 分钟")
        set_accessible(self._sunrise_offset, "日出切换时间偏移")
        set_accessible(self._sunset_offset, "日落切换时间偏移")
        location_form.addRow("日出偏移", self._sunrise_offset)
        location_form.addRow("日落偏移", self._sunset_offset)
        self._location_hint = QLabel("请选择城市或填写坐标；不会静默使用默认位置。")
        self._location_hint.setObjectName("cardDescription")
        self._location_hint.setWordWrap(True)
        location_form.addRow("", self._location_hint)
        rule_card.body.addWidget(self._location_widget)

        action_row = QHBoxLayout()
        action_row.addStretch()
        self._save_button = QPushButton("保存自动化设置")
        self._save_button.setObjectName("primaryButton")
        set_accessible(self._save_button, "保存自动化设置")
        action_row.addWidget(self._save_button)
        rule_card.body.addLayout(action_row)
        self.layout.addWidget(rule_card)

        context_card = Card("当前情境", "只使用本机系统状态，不读取窗口标题或屏幕内容。")
        context_row = QHBoxLayout()
        self._context_status = QLabel("正在检测当前情境…")
        self._context_status.setWordWrap(True)
        self._context_status.setObjectName("statusValue")
        self._resume_context_button = QPushButton("本次场景继续提醒")
        self._resume_context_button.setObjectName("secondaryButton")
        set_accessible(self._context_status, "当前智能免打扰状态")
        set_accessible(self._resume_context_button, "在本次场景继续休息提醒")
        context_row.addWidget(self._context_status, 1)
        context_row.addWidget(self._resume_context_button)
        context_card.body.addLayout(context_row)
        self.layout.addWidget(context_card)

        smart_card = Card(
            "智能免打扰",
            "全屏、演示或离开电脑时临时暂停提醒；不会修改原来的功能开关。",
        )
        smart_form = QFormLayout()
        smart_form.setHorizontalSpacing(24)
        smart_form.setVerticalSpacing(10)
        self._smart_pause_toggle = QCheckBox("启用情境感知")
        self._fullscreen_pause_toggle = QCheckBox("全屏、演示和游戏时暂停")
        self._natural_rest_toggle = QCheckBox(
            "离开 2 分钟后暂停，达到 5 分钟视为自然休息"
        )
        set_accessible(self._smart_pause_toggle, "启用智能免打扰")
        set_accessible(self._fullscreen_pause_toggle, "全屏时自动暂停")
        set_accessible(self._natural_rest_toggle, "启用自然休息")
        smart_form.addRow("总开关", self._smart_pause_toggle)
        smart_form.addRow("全屏场景", self._fullscreen_pause_toggle)
        smart_form.addRow("离开电脑", self._natural_rest_toggle)
        smart_card.body.addLayout(smart_form)
        self.layout.addWidget(smart_card)

        apps_card = Card(
            "应用例外",
            "仅保存程序文件名。添加后可分别控制休息、专注、色温与调暗。",
        )
        app_actions = QHBoxLayout()
        self._current_app_label = QLabel("当前应用：尚未识别")
        self._current_app_label.setObjectName("cardDescription")
        self._add_current_app_button = QPushButton("添加当前应用")
        self._add_current_app_button.setObjectName("secondaryButton")
        self._choose_app_button = QPushButton("选择可执行程序…")
        self._choose_app_button.setObjectName("secondaryButton")
        set_accessible(self._add_current_app_button, "添加当前前台应用")
        set_accessible(self._choose_app_button, "选择要添加例外规则的程序")
        app_actions.addWidget(self._current_app_label, 1)
        app_actions.addWidget(self._add_current_app_button)
        app_actions.addWidget(self._choose_app_button)
        apps_card.body.addLayout(app_actions)

        self._rules_table = QTableWidget(0, 6)
        self._rules_table.setHorizontalHeaderLabels(
            (
                "应用",
                "暂停休息",
                "隐藏专注",
                "暂停色温",
                "暂停调暗",
                "",
            )
        )
        self._rules_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._rules_table.setSelectionMode(QAbstractItemView.NoSelection)
        self._rules_table.verticalHeader().setVisible(False)
        self._rules_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch
        )
        for column in range(1, 6):
            self._rules_table.horizontalHeader().setSectionResizeMode(
                column, QHeaderView.ResizeToContents
            )
        self._rules_table.setMinimumHeight(150)
        self._rules_table.setAccessibleName("智能免打扰应用规则")
        apps_card.body.addWidget(self._rules_table)
        self.layout.addWidget(apps_card)
        self.layout.addStretch()
        self._update_mode_visibility()
        self._city_changed(0)

    def _connect_signals(self) -> None:
        self._schedule_toggle.toggled.connect(self._toggle_schedule)
        self._mode_combo.currentIndexChanged.connect(self._update_mode_visibility)
        self._city_combo.currentIndexChanged.connect(self._city_changed)
        self._save_button.clicked.connect(lambda: self._save_schedule())
        self._smart_pause_toggle.toggled.connect(
            self._controller.set_smart_pause_enabled
        )
        self._fullscreen_pause_toggle.toggled.connect(
            self._controller.set_fullscreen_pause_enabled
        )
        self._natural_rest_toggle.toggled.connect(
            self._controller.set_natural_rest_enabled
        )
        self._add_current_app_button.clicked.connect(self._add_current_app)
        self._choose_app_button.clicked.connect(self._choose_app)
        self._resume_context_button.clicked.connect(
            self._controller.resume_breaks_for_current_context
        )
        self._controller.state_changed.connect(self.render)

    def _update_mode_visibility(self, *_args) -> None:
        fixed = self._mode_combo.currentData() == "fixed"
        self._fixed_widget.setVisible(fixed)
        self._location_widget.setVisible(not fixed)

    def _city_changed(self, index: int) -> None:
        value = self._city_combo.itemData(index)
        if isinstance(value, tuple):
            with QSignalBlocker(self._latitude):
                self._latitude.setValue(value[0])
            with QSignalBlocker(self._longitude):
                self._longitude.setValue(value[1])
        editable = value == "custom"
        self._latitude.setEnabled(editable)
        self._longitude.setEnabled(editable)

    def _toggle_schedule(self, enabled: bool) -> None:
        if self._rendering:
            return
        if enabled and self._mode_combo.currentData() == "sun" and self._city_combo.currentData() is None:
            with QSignalBlocker(self._schedule_toggle):
                self._schedule_toggle.setChecked(False)
            self._location_hint.setText("请先选择城市或自定义坐标，再启用自动化。")
            self._city_combo.setFocus()
            return
        self._save_schedule(enabled=enabled)

    def _save_schedule(self, enabled: bool | None = None) -> None:
        if enabled is None:
            enabled = self._schedule_toggle.isChecked()
        mode = self._mode_combo.currentData()
        days = [
            index
            for index, button in enumerate(self._weekday_buttons)
            if button.isChecked()
        ]
        common = {
            "days": days,
            "day_profile": self._day_profile_combo.currentData(),
            "night_profile": self._night_profile_combo.currentData(),
            "sunrise_offset": self._sunrise_offset.value(),
            "sunset_offset": self._sunset_offset.value(),
        }
        if mode == "fixed":
            self._call_set_schedule(
                enabled,
                mode="fixed",
                on_time=self._on_time.time().toString("HH:mm"),
                off_time=self._off_time.time().toString("HH:mm"),
                **common,
            )
        else:
            if self._city_combo.currentData() is None:
                self._call_set_schedule(enabled, mode="sun", **common)
                return
            latitude = self._latitude.value()
            longitude = self._longitude.value()
            selected_city = self._city_combo.currentText()
            if self._city_combo.currentData() == "custom":
                selected_city = ""
            self._call_set_schedule(
                enabled,
                mode="sun",
                latitude=latitude,
                longitude=longitude,
                city=selected_city,
                **common,
            )

    def _call_set_schedule(self, enabled: bool, **kwargs):
        """Use v4 arguments when the controller supports them."""
        method = self._controller.set_schedule
        extended_names = {
            "city",
            "day_profile",
            "night_profile",
            "sunrise_offset",
            "sunset_offset",
        }
        try:
            parameters = inspect.signature(method).parameters.values()
            supports_extended = any(
                parameter.kind is inspect.Parameter.VAR_KEYWORD
                for parameter in parameters
            ) or extended_names.issubset(
                {parameter.name for parameter in parameters}
            )
        except (TypeError, ValueError):
            supports_extended = False
        if not supports_extended:
            kwargs = {
                key: value
                for key, value in kwargs.items()
                if key not in extended_names
            }
        return method(enabled, **kwargs)

    def _add_current_app(self) -> None:
        app_id = _basename_app_id(first_state_value(
            self._last_state, "context.foreground_app_id", default=""
        ) or first_state_value(
            self._last_state, "context.recent_app_id", default=""
        ))
        if not app_id:
            self._context_status.setText(
                "尚未识别到外部前台应用，请先切换到目标应用后再返回。"
            )
            return
        self._controller.upsert_app_rule({
            "app_id": app_id,
            "breaks": True,
            "focus": True,
            "filter": False,
            "dimmer": False,
        })

    def _choose_app(self) -> None:
        path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "选择应用程序",
            "",
            "Windows 应用程序 (*.exe)",
        )
        if not path:
            return
        app_id = _basename_app_id(path)
        if not app_id:
            self._context_status.setText("请选择有效的 Windows 可执行程序（.exe）。")
            return
        self._controller.upsert_app_rule(
            {
                "app_id": app_id,
                "breaks": True,
                "focus": True,
                "filter": False,
                "dimmer": False,
            }
        )

    def _update_app_rule(self, app_id: str, feature: str, checked: bool) -> None:
        current = dict(self._rules_by_app.get(app_id, {}))
        current.update({
            "app_id": app_id,
            "breaks": bool(current.get("breaks", True)),
            "focus": bool(current.get("focus", True)),
            "filter": bool(current.get("filter", False)),
            "dimmer": bool(current.get("dimmer", False)),
        })
        current[feature] = bool(checked)
        self._controller.upsert_app_rule(current)

    def _render_app_rules(self, rules) -> None:
        normalized = []
        for rule in rules:
            getter = rule.get if isinstance(rule, dict) else lambda key, default=None: getattr(
                rule, key, default
            )
            app_id = _basename_app_id(getter("app_id", ""))
            if app_id:
                normalized.append({
                    "app_id": app_id,
                    "breaks": bool(getter("breaks", True)),
                    "focus": bool(getter("focus", True)),
                    "filter": bool(getter("filter", False)),
                    "dimmer": bool(getter("dimmer", False)),
                })
        signature = tuple(
            (rule["app_id"], rule["breaks"], rule["focus"], rule["filter"], rule["dimmer"])
            for rule in normalized
        )
        if signature == self._rules_signature:
            return
        self._rules_signature = signature
        self._rules_by_app = {rule["app_id"]: rule for rule in normalized}
        self._rules_table.setRowCount(len(normalized))
        for row, rule in enumerate(normalized):
            self._rules_table.setItem(row, 0, QTableWidgetItem(rule["app_id"]))
            for column, feature in enumerate(
                ("breaks", "focus", "filter", "dimmer"), start=1
            ):
                checkbox = QCheckBox()
                checkbox.setChecked(rule[feature])
                checkbox.setAccessibleName(
                    f"{rule['app_id']} · {feature_description(feature)}"
                )
                checkbox.toggled.connect(
                    lambda checked, app=rule["app_id"], key=feature: self._update_app_rule(
                        app, key, checked
                    )
                )
                self._rules_table.setCellWidget(row, column, checkbox)
            remove = QPushButton("删除")
            remove.setObjectName("quietButton")
            remove.clicked.connect(
                lambda checked=False, app=rule["app_id"]: self._controller.remove_app_rule(app)
            )
            self._rules_table.setCellWidget(row, 5, remove)

    def render(self, state) -> None:
        self._rendering = True
        self._last_state = state
        try:
            enabled = bool(first_state_value(state, "automation.enabled", default=False))
            mode = str(first_state_value(state, "automation.mode", default="sun"))
            next_event = str(first_state_value(state, "automation.next_event", default=""))
            next_at = first_state_value(state, "automation.next_event_at", default=None)
            next_profile = str(first_state_value(
                state, "automation.next_profile", default=""
            ))
            manual_override = bool(first_state_value(
                state, "automation.manual_override", default=False
            ))
            on_time = str(first_state_value(state, "automation.on_time", default="19:00"))
            off_time = str(first_state_value(state, "automation.off_time", default="07:30"))
            days = tuple(first_state_value(
                state, "automation.days", default=(0, 1, 2, 3, 4)
            ))
            day_profile = str(first_state_value(
                state, "automation.day_profile", default="office"
            ))
            night_profile = str(first_state_value(
                state, "automation.night_profile", default="night"
            ))
            sunrise_offset = int(first_state_value(
                state, "automation.sunrise_offset", default=0
            ))
            sunset_offset = int(first_state_value(
                state, "automation.sunset_offset", default=0
            ))
            if not next_profile:
                next_profile = (
                    day_profile
                    if next_event in {"off", "sunrise", "disable"}
                    else night_profile
                )
            available = bool(first_state_value(
                state, "capabilities.automation_available", default=True
            ))
            city = str(first_state_value(state, "general.city", default=""))
            latitude = first_state_value(state, "general.latitude", default=None)
            longitude = first_state_value(state, "general.longitude", default=None)
            location_configured = bool(first_state_value(
                state, "general.location_configured", default=False
            ))
            smart_enabled = bool(first_state_value(
                state, "automation.smart_pause.enabled", default=True
            ))
            fullscreen_enabled = bool(first_state_value(
                state,
                "automation.smart_pause.fullscreen_enabled",
                default=True,
            ))
            natural_rest_enabled = bool(first_state_value(
                state,
                "automation.smart_pause.natural_rest_enabled",
                default=True,
            ))
            app_rules = tuple(first_state_value(
                state, "automation.smart_pause.app_rules", default=()
            ))

            with QSignalBlocker(self._schedule_toggle):
                self._schedule_toggle.setChecked(enabled)
            index = self._mode_combo.findData(mode)
            if index < 0 and mode in ("sunrise_sunset", "astral"):
                index = self._mode_combo.findData("sun")
            if index >= 0:
                with QSignalBlocker(self._mode_combo):
                    self._mode_combo.setCurrentIndex(index)
            self._update_mode_visibility()
            parsed_on = QTime.fromString(on_time, "HH:mm")
            parsed_off = QTime.fromString(off_time, "HH:mm")
            if parsed_on.isValid():
                self._on_time.setTime(parsed_on)
            if parsed_off.isValid():
                self._off_time.setTime(parsed_off)
            for day_index, button in enumerate(self._weekday_buttons):
                button.setChecked(day_index in days)
            for combo, profile in (
                (self._day_profile_combo, day_profile),
                (self._night_profile_combo, night_profile),
            ):
                profile_index = combo.findData(profile)
                if profile_index >= 0:
                    with QSignalBlocker(combo):
                        combo.setCurrentIndex(profile_index)
            with QSignalBlocker(self._sunrise_offset):
                self._sunrise_offset.setValue(sunrise_offset)
            with QSignalBlocker(self._sunset_offset):
                self._sunset_offset.setValue(sunset_offset)

            if not enabled:
                event_text = "尚未启用自动化"
            elif next_event and next_at:
                profile_label = _PROFILE_LABELS.get(next_profile, "自定义")
                action = (
                    f"切换到{profile_label}方案"
                    if profile_label
                    else schedule_event_description(next_event)
                )
                if isinstance(next_at, datetime):
                    when = next_at.astimezone().strftime("%m月%d日 %H:%M")
                else:
                    when = str(next_at)
                event_text = f"{when} · {action}"
            else:
                event_text = "正在计算下一次自动切换…"
            self._next_event.setText(event_text)
            self._next_event.setAccessibleName(f"下一次动作：{event_text}")
            self._override_label.setVisible(manual_override)
            if city:
                city_index = self._city_combo.findText(city)
                if city_index >= 0:
                    with QSignalBlocker(self._city_combo):
                        self._city_combo.setCurrentIndex(city_index)
                    self._city_changed(city_index)
            elif location_configured and latitude is not None and longitude is not None:
                custom_index = self._city_combo.findData("custom")
                with QSignalBlocker(self._city_combo):
                    self._city_combo.setCurrentIndex(custom_index)
                self._city_changed(custom_index)
                with QSignalBlocker(self._latitude):
                    self._latitude.setValue(float(latitude))
                with QSignalBlocker(self._longitude):
                    self._longitude.setValue(float(longitude))
            if not location_configured:
                self._location_hint.setText("请选择城市或填写坐标；不会静默使用默认位置。")
            else:
                self._location_hint.setText("位置仅保存在本机，用于计算日出与日落。")
            self._schedule_toggle.setEnabled(available)
            self._save_button.setEnabled(available)

            for toggle, checked in (
                (self._smart_pause_toggle, smart_enabled),
                (self._fullscreen_pause_toggle, fullscreen_enabled),
                (self._natural_rest_toggle, natural_rest_enabled),
            ):
                with QSignalBlocker(toggle):
                    toggle.setChecked(checked)
            self._fullscreen_pause_toggle.setEnabled(smart_enabled)
            self._natural_rest_toggle.setEnabled(smart_enabled)

            app_id = _basename_app_id(first_state_value(
                state, "context.foreground_app_id", default=""
            ) or first_state_value(
                state, "context.recent_app_id", default=""
            ))
            self._current_app_label.setText(
                f"当前应用：{app_id}" if app_id else "当前应用：尚未识别"
            )
            reasons = tuple(first_state_value(
                state,
                "effective_policy.breaks.suppressed_by",
                default=(),
            ))
            if reasons:
                reason_text = "、".join(
                    suppression_reason_description(reason) for reason in reasons
                )
                resume = str(first_state_value(
                    state,
                    "effective_policy.breaks.resume_condition",
                    default="情境结束后恢复",
                ))
                self._context_status.setText(
                    f"休息提醒已开启，当前因{reason_text}暂停 · {resume}"
                )
            else:
                session = str(first_state_value(state, "context.session", default="active"))
                fullscreen = bool(first_state_value(
                    state, "context.fullscreen", default=False
                ))
                if session != "active":
                    self._context_status.setText("当前会话不可交互，提醒已安全让出。")
                elif fullscreen:
                    self._context_status.setText("检测到全屏应用，正在确认稳定状态…")
                else:
                    self._context_status.setText("当前没有需要暂停的情境。")
            self._resume_context_button.setVisible(
                bool(reasons)
                and not {
                    "locked",
                    "session_locked",
                    "suspended",
                    "system_suspended",
                }.intersection(reasons)
            )
            self._render_app_rules(app_rules)
        finally:
            self._rendering = False
