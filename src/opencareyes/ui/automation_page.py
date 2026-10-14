"""Context controls for breaks and focus; screen dimming remains manual."""

from __future__ import annotations

import ntpath

from PySide6.QtCore import QSignalBlocker
from PySide6.QtWidgets import (
    QAbstractItemView, QBoxLayout, QCheckBox, QFileDialog, QFormLayout,
    QHeaderView, QLabel, QPushButton, QTableWidget, QTableWidgetItem,
)

from opencareyes.application.status_presenter import StatusPresenter

from opencareyes.ui.widgets import (
    Card, PageHeader, ScrollPage, feature_description, first_state_value,
    set_accessible, suppression_reason_description,
)


def _basename_app_id(path: object) -> str:
    value = ntpath.basename(str(path).strip()).lower()
    if not value.endswith(".exe") or len(value) > 128:
        return ""
    return value


class AutomationPage(ScrollPage):
    """Keep the legacy class name for saved page routes."""

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self._controller = controller
        self._last_state = controller.state
        self._rules_signature = None
        self._build_ui()
        self._connect_signals()
        self.render(controller.state)

    def _build_ui(self) -> None:
        self.layout.addWidget(PageHeader(
            "免打扰", "按使用情境暂停休息和专注效果，手动调暗保持不变。",
        ))
        context_card = Card("当前情境", "只使用本机系统状态，不读取窗口标题或屏幕内容。")
        context_row = self._context_row = QBoxLayout(QBoxLayout.LeftToRight)
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
            "休息的全屏行为在“休息”页选择；这里设置专注避让、离开电脑和应用例外。",
        )
        smart_form = QFormLayout()
        smart_form.setHorizontalSpacing(24)
        smart_form.setVerticalSpacing(10)
        self._smart_pause_toggle = QCheckBox("启用情境感知")
        self._fullscreen_pause_toggle = QCheckBox("全屏或演示时隐藏专注遮罩")
        self._natural_rest_toggle = QCheckBox("离开电脑时暂停提醒")
        set_accessible(self._smart_pause_toggle, "启用智能免打扰")
        set_accessible(self._fullscreen_pause_toggle, "全屏时隐藏专注遮罩")
        set_accessible(self._natural_rest_toggle, "启用自然休息")
        smart_form.addRow("总开关", self._smart_pause_toggle)
        smart_form.addRow("专注避让", self._fullscreen_pause_toggle)
        smart_form.addRow("离开电脑", self._natural_rest_toggle)
        natural_rest_hint = QLabel('离开 2 分钟后暂停；达到 5 分钟按自然休息处理。')
        natural_rest_hint.setWordWrap(True)
        natural_rest_hint.setObjectName('cardDescription')
        smart_form.addRow('', natural_rest_hint)
        smart_card.body.addLayout(smart_form)
        self.layout.addWidget(smart_card)

        apps_card = Card(
            "应用例外",
            "只暂停休息提醒和专注遮罩，不改变手动调暗。仅保存程序文件名。",
        )
        app_actions = self._app_actions = QBoxLayout(QBoxLayout.LeftToRight)
        self._current_app_label = QLabel("当前应用：尚未识别")
        self._current_app_label.setObjectName("cardDescription")
        self._current_app_label.setWordWrap(True)
        self._add_current_app_button = QPushButton("添加当前应用")
        self._add_current_app_button.setObjectName("secondaryButton")
        self._choose_app_button = QPushButton("选择程序…")
        self._choose_app_button.setObjectName("secondaryButton")
        set_accessible(self._add_current_app_button, "添加当前前台应用")
        set_accessible(self._choose_app_button, "选择要添加例外规则的程序")
        app_actions.addWidget(self._current_app_label, 1)
        app_actions.addWidget(self._add_current_app_button)
        app_actions.addWidget(self._choose_app_button)
        apps_card.body.addLayout(app_actions)

        self._rules_table = QTableWidget(0, 4)
        self._rules_table.setHorizontalHeaderLabels(
            (
                "应用",
                "暂停休息",
                "隐藏专注",
                "",
            )
        )
        self._rules_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._rules_table.setSelectionMode(QAbstractItemView.NoSelection)
        self._rules_table.verticalHeader().setVisible(False)
        self._rules_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch
        )
        for column in range(1, 4):
            self._rules_table.horizontalHeader().setSectionResizeMode(
                column, QHeaderView.ResizeToContents
            )
        self._rules_table.setMinimumHeight(150)
        self._rules_table.setAccessibleName("智能免打扰应用规则")
        apps_card.body.addWidget(self._rules_table)
        self.layout.addWidget(apps_card)
        self.layout.addStretch()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        compact = self.viewport().width() < 600
        direction = QBoxLayout.TopToBottom if compact else QBoxLayout.LeftToRight
        for row in (self._context_row, self._app_actions):
            row.setDirection(direction)
        self._rules_table.setHorizontalHeaderLabels(
            ('程序', '休息', '专注', '') if compact
            else ('应用', '暂停休息', '隐藏专注', '')
        )

    def _connect_signals(self) -> None:
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
                ("breaks", "focus"), start=1
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
            self._rules_table.setCellWidget(row, 3, remove)

    def render(self, state) -> None:
        self._last_state = state
        smart_enabled = bool(first_state_value(
            state, "automation.smart_pause.enabled", default=True,
        ))
        fullscreen_enabled = bool(first_state_value(
            state, "automation.smart_pause.fullscreen_enabled", default=True,
        ))
        natural_rest_enabled = bool(first_state_value(
            state, "automation.smart_pause.natural_rest_enabled", default=True,
        ))
        app_rules = tuple(first_state_value(
            state, "automation.smart_pause.app_rules", default=(),
        ))
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
            elif fullscreen or StatusPresenter.is_fullscreen_context(state):
                mode = str(first_state_value(state, 'breaks.fullscreen_mode', default='pause'))
                self._context_status.setText(
                    "当前为全屏，休息继续计时并按所选方式提醒。"
                    if mode == 'continue'
                    else "检测到全屏应用，正在确认稳定状态…"
                )
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
