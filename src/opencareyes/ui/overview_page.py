"""At-a-glance overview and global pause controls."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QMenu, QPushButton, QToolButton

from opencareyes.ui.widgets import (
    Card,
    PageHeader,
    ScrollPage,
    StatusCard,
    display_backend_description,
    first_state_value,
    format_duration,
    schedule_event_description,
    set_accessible,
    suppression_reason_description,
    temperature_description,
)


_PROFILE_NAMES = {
    "office": "办公方案",
    "reading": "阅读方案",
    "night": "夜间方案",
    "game": "游戏方案",
    "movie": "观影方案",
    "custom": "自定义方案",
}


class OverviewPage(ScrollPage):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self._controller = controller
        self._build_ui()
        self._controller.state_changed.connect(self.render)
        break_tick = getattr(self._controller, "break_tick", None)
        if break_tick is not None:
            break_tick.connect(self._render_break_tick)
        self.render(controller.state)

    def _render_break_tick(self, remaining: int, _total: int) -> None:
        state = self._controller.state
        enabled = bool(first_state_value(state, "breaks.enabled", default=False))
        phase = str(first_state_value(state, "breaks.phase", default="stopped"))
        paused = bool(first_state_value(state, "breaks.paused", default=False))
        suppressed = tuple(first_state_value(
            state,
            "effective_policy.breaks.suppressed_by",
            default=(),
        ))
        if not enabled or phase == "stopped" or suppressed:
            return
        remaining = max(0, int(remaining))
        if phase == "resting":
            value = f"正在休息 · 剩余 {format_duration(remaining)}"
        elif phase == "prompting":
            value = "该休息一下了"
        elif phase == "snoozed":
            value = f"已延后 · {format_duration(remaining)} 后再次提醒"
        elif paused:
            value = f"计时已暂停 · 剩余 {format_duration(remaining)}"
        else:
            value = f"{format_duration(remaining)} 后休息"
        self._break_card.value.setText(value)
        self._break_card.setAccessibleName(
            f"{value}，{self._break_card.badge.text()}"
        )

    def _build_ui(self) -> None:
        header_row = QHBoxLayout()
        header_row.addWidget(PageHeader(
            "总览",
            "核心状态集中在这里。日常使用可以关闭窗口，OpenCareEyes 会继续驻留托盘。",
        ), 1)
        self._pause_button = QToolButton()
        self._pause_button.setText("暂停全部")
        self._pause_button.setObjectName("primaryButton")
        self._pause_button.setMinimumWidth(120)
        self._pause_button.setPopupMode(QToolButton.InstantPopup)
        pause_menu = QMenu(self._pause_button)
        pause_menu.addAction("暂停 30 分钟").triggered.connect(
            lambda: self._controller.pause_all(minutes=30)
        )
        pause_menu.addAction("暂停 1 小时").triggered.connect(
            lambda: self._controller.pause_all(minutes=60)
        )
        pause_menu.addAction("直到下一次自动切换").triggered.connect(
            lambda: self._controller.pause_all(minutes=None, until_next_schedule=True)
        )
        pause_menu.addAction("直到手动恢复").triggered.connect(
            lambda: self._controller.pause_all(minutes=None)
        )
        self._pause_button.setMenu(pause_menu)
        set_accessible(self._pause_button, "暂停全部效果")

        self._resume_button = QPushButton("恢复全部")
        self._resume_button.setObjectName("primaryButton")
        self._resume_button.clicked.connect(self._controller.resume_all)
        set_accessible(self._resume_button, "恢复全部效果")
        header_row.addWidget(self._pause_button, 0, Qt.AlignTop)
        header_row.addWidget(self._resume_button, 0, Qt.AlignTop)
        self.layout.addLayout(header_row)

        self._pause_banner = Card()
        banner_row = QHBoxLayout()
        self._pause_banner_title = QLabel("全部效果已暂停")
        self._pause_banner_title.setObjectName("sectionLead")
        self._pause_banner_detail = QLabel("")
        self._pause_banner_detail.setObjectName("cardDescription")
        banner_row.addWidget(self._pause_banner_title)
        banner_row.addStretch()
        banner_row.addWidget(self._pause_banner_detail)
        self._pause_banner.body.addLayout(banner_row)
        self.layout.addWidget(self._pause_banner)

        self._runtime_card = Card("当前实际效果", "显示的是实际运行状态，不只是保存的开关。")
        runtime_row = QHBoxLayout()
        runtime_text = QHBoxLayout()
        self._runtime_status = QLabel("正在检查显示效果…")
        self._runtime_status.setObjectName("sectionLead")
        self._activity_status = QLabel("")
        self._activity_status.setObjectName("cardDescription")
        runtime_text.addWidget(self._runtime_status)
        runtime_text.addWidget(self._activity_status)
        runtime_text.addStretch()
        self._restore_display_button = QPushButton("恢复原始显示")
        self._restore_display_button.setObjectName("quietButton")
        restorer = getattr(self._controller, "restore_display_effects", None)
        self._restore_display_button.setEnabled(callable(restorer))
        if callable(restorer):
            self._restore_display_button.clicked.connect(restorer)
        set_accessible(
            self._restore_display_button,
            "恢复原始显示并关闭屏幕效果",
        )
        runtime_row.addLayout(runtime_text, 1)
        runtime_row.addWidget(self._restore_display_button)
        self._runtime_card.body.addLayout(runtime_row)
        self.layout.addWidget(self._runtime_card)

        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(16)
        self._display_card = StatusCard("屏幕舒适度")
        self._break_card = StatusCard("休息节奏")
        self._resume_context_button = QPushButton("本次场景继续提醒")
        self._resume_context_button.setObjectName("secondaryButton")
        self._resume_context_button.clicked.connect(
            self._controller.resume_breaks_for_current_context
        )
        set_accessible(self._resume_context_button, "本次场景继续休息提醒")
        self._break_card.body.addWidget(self._resume_context_button)
        self._focus_card = StatusCard("专注模式")
        self._automation_card = StatusCard("自动化")
        grid.addWidget(self._display_card, 0, 0)
        grid.addWidget(self._break_card, 0, 1)
        grid.addWidget(self._focus_card, 1, 0)
        grid.addWidget(self._automation_card, 1, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        self.layout.addLayout(grid)

        quick_card = Card("快速方案", "只改变色温与调暗，不会修改休息和专注设置。")
        quick_row = QHBoxLayout()
        for key, label in (("office", "办公"), ("reading", "阅读"), ("night", "夜间"), ("game", "游戏")):
            button = QPushButton(label)
            button.setObjectName("profileButton")
            button.clicked.connect(
                lambda checked=False, profile=key: self._controller.apply_display_profile(profile)
            )
            set_accessible(button, f"应用{label}显示方案")
            quick_row.addWidget(button)
        quick_row.addStretch()
        quick_card.body.addLayout(quick_row)
        self.layout.addWidget(quick_card)
        self.layout.addStretch()

    @staticmethod
    def _format_event(event: str, at) -> str:
        if not event or not at:
            return "等待计算"
        action = schedule_event_description(event)
        if isinstance(at, datetime):
            when = at.astimezone().strftime("%m月%d日 %H:%M")
        else:
            when = str(at)
        return f"{when} · {action}"

    def render(self, state) -> None:
        paused = bool(first_state_value(state, "global_pause.active", default=False))
        pause_mode = str(first_state_value(state, "global_pause.mode", default="none"))
        pause_until = first_state_value(state, "global_pause.until", default=None)
        self._pause_banner.setVisible(paused)
        self._pause_button.setVisible(not paused)
        self._resume_button.setVisible(paused)
        pause_detail = {
            "next_schedule": "将在下一次自动切换时恢复",
            "manual": "等待手动恢复",
            "timed": "稍后自动恢复",
        }.get(pause_mode, "")
        if pause_until:
            if isinstance(pause_until, datetime):
                pause_detail = f"恢复时间 {pause_until.astimezone().strftime('%H:%M')}"
            else:
                pause_detail = f"恢复时间 {pause_until}"
        self._pause_banner_detail.setText(pause_detail)

        filter_enabled = bool(first_state_value(state, "display.filter_enabled", default=False))
        dimmer_enabled = bool(first_state_value(state, "display.dimmer_enabled", default=False))
        filter_suppressed = tuple(first_state_value(
            state, "effective_policy.filter.suppressed_by", default=()
        ))
        dimmer_suppressed = tuple(first_state_value(
            state, "effective_policy.dimmer.suppressed_by", default=()
        ))
        filter_effective = bool(first_state_value(
            state,
            "effective_policy.filter.effective_enabled",
            default=filter_enabled,
        ))
        dimmer_effective = bool(first_state_value(
            state,
            "effective_policy.dimmer.effective_enabled",
            default=dimmer_enabled,
        ))
        temp = int(first_state_value(state, "display.color_temperature", default=6500))
        dim_level = int(first_state_value(state, "display.dim_level", default=0))
        profile = str(first_state_value(state, "display.preset", default="custom"))
        display_desired = filter_enabled or dimmer_enabled
        display_enabled = filter_effective or dimmer_effective
        display_suppressed = tuple(dict.fromkeys(
            (*filter_suppressed, *dimmer_suppressed)
        ))
        dim_percent = round(dim_level * 100 / 200)
        display_health = str(first_state_value(
            state,
            "display_health.status",
            default="active" if display_enabled else "ready",
        ))
        display_backend = display_backend_description(first_state_value(
            state,
            "display_health.backend",
            default="gamma_ramp",
        ))
        health_message = str(first_state_value(
            state,
            "display_health.message",
            default="",
        ))
        hdr_active = bool(first_state_value(
            state,
            "display_health.hdr_active",
            default=False,
        ))
        pending = bool(first_state_value(
            state,
            "display_health.pending",
            default=False,
        ))
        if hdr_active:
            self._runtime_status.setText("HDR 已开启 · 色温安全暂停")
        elif pending:
            self._runtime_status.setText("正在应用显示效果…")
        elif display_health in {"error", "failed", "degraded", "unavailable"}:
            self._runtime_status.setText(health_message or "显示效果需要检查")
        elif display_suppressed:
            reasons = "、".join(
                suppression_reason_description(reason)
                for reason in display_suppressed
            )
            self._runtime_status.setText(f"显示效果因{reasons}暂停")
        elif display_enabled:
            self._runtime_status.setText(f"显示效果已验证 · {display_backend}")
        else:
            self._runtime_status.setText("显示效果未启用")
        self._display_card.set_status(
            display_enabled,
            (
                "当前因 HDR 暂停"
                if hdr_active
                else "当前受运行策略暂停"
                if display_suppressed
                else _PROFILE_NAMES.get(profile, "自定义方案")
            ),
            f"{temperature_description(temp)} {temp}K · 调暗 {dim_percent}%",
            active_text=(
                "自动暂停"
                if display_desired and (display_suppressed or hdr_active)
                else "运行中"
            ),
        )

        break_enabled = bool(first_state_value(state, "breaks.enabled", default=False))
        break_phase = str(first_state_value(state, "breaks.phase", default="stopped"))
        break_paused = bool(first_state_value(state, "breaks.paused", default=False))
        break_suppressed = tuple(first_state_value(
            state, "effective_policy.breaks.suppressed_by", default=()
        ))
        break_resume = str(first_state_value(
            state, "effective_policy.breaks.resume_condition", default=""
        ))
        remaining = first_state_value(state, "breaks.remaining", default=0)
        short_remaining = first_state_value(
            state,
            "break_cadence.short_remaining",
            "breaks.cadence.short_remaining",
            "breaks.short_remaining",
            default=remaining,
        )
        long_remaining = first_state_value(
            state,
            "break_cadence.long_remaining",
            "breaks.cadence.long_remaining",
            "breaks.long_remaining",
            default=None,
        )
        self._activity_status.setText(
            (
                f"短休息 {format_duration(short_remaining)}"
                + (
                    f" · 长休息 {format_duration(long_remaining)}"
                    if long_remaining is not None
                    else ""
                )
            )
            if break_enabled
            else "休息计时未启用"
        )
        if break_suppressed:
            reason = "、".join(
                suppression_reason_description(item)
                for item in break_suppressed
            )
            break_value = f"因{reason}暂停"
        elif break_phase == "resting":
            break_value = "正在休息"
        elif break_phase == "prompting":
            break_value = "该休息一下了"
        elif break_paused:
            break_value = "计时已暂停"
        elif break_enabled:
            break_value = f"{format_duration(remaining)} 后休息"
        else:
            break_value = "未启用"
        break_detail = {
            "20-20-20": "20-20-20",
            "pomodoro": "番茄钟",
            "balanced": "平衡节奏",
            "custom": "自定义",
        }.get(
            str(first_state_value(state, "breaks.mode", default="custom")), "自定义"
        )
        if break_suppressed:
            break_detail = break_resume or "当前情境结束后恢复"
        self._break_card.set_status(
            break_enabled,
            break_value,
            break_detail,
            active_text=(
                "自动暂停" if break_suppressed
                else "已暂停" if break_paused
                else "运行中"
            ),
        )
        self._resume_context_button.setVisible(
            bool(break_suppressed)
            and not {
                "locked",
                "session_locked",
                "suspended",
                "system_suspended",
            }.intersection(break_suppressed)
        )

        focus_enabled = bool(first_state_value(state, "focus.enabled", default=False))
        focus_suppressed = tuple(first_state_value(
            state, "effective_policy.focus.suppressed_by", default=()
        ))
        focus_level = int(first_state_value(state, "focus.dim_level", default=0))
        focus_ends = first_state_value(state, "focus.session_ends_at", default=None)
        focus_detail = f"背景暗化 {round(focus_level * 100 / 255)}%"
        if isinstance(focus_ends, datetime):
            focus_detail += f" · {focus_ends.astimezone().strftime('%H:%M')} 结束"
        self._focus_card.set_status(
            focus_enabled,
            "情境中暂时隐藏" if focus_suppressed else "保持专注" if focus_enabled else "未启用",
            focus_detail,
        )

        automation_enabled = bool(first_state_value(state, "automation.enabled", default=False))
        smart_enabled = bool(first_state_value(
            state, "automation.smart_pause.enabled", default=True
        ))
        event = str(first_state_value(state, "automation.next_event", default=""))
        event_at = first_state_value(state, "automation.next_event_at", default=None)
        override = bool(first_state_value(state, "automation.manual_override", default=False))
        context_app = str(first_state_value(state, "context.foreground_app_id", default=""))
        context_fullscreen = bool(first_state_value(state, "context.fullscreen", default=False))
        context_detail = (
            f"当前全屏：{context_app or '未知应用'}"
            if context_fullscreen
            else "显示方案自动切换"
        )
        self._automation_card.set_status(
            automation_enabled or smart_enabled,
            (
                break_value
                if break_suppressed
                else self._format_event(event, event_at)
                if automation_enabled
                else "智能免打扰已启用"
                if smart_enabled
                else "未启用"
            ),
            (
                break_resume
                if break_suppressed
                else "手动调整将在此时恢复自动化"
                if override
                else context_detail
            ),
            active_text="运行中" if automation_enabled else "情境感知",
        )
