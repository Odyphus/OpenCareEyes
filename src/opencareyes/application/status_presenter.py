"""Pure presentation projection for companion-oriented status surfaces.

The projector deliberately has no Qt dependency.  It turns the immutable
application state into a small, stable value object that can be shared by the
companion home, tray and bubble without duplicating product wording.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from opencareyes.state import AppState


@dataclass(frozen=True, slots=True)
class FeatureStatusPresentation:
    """One feature's preference and its real runtime result."""

    feature_id: Literal["filter", "dimmer", "breaks", "focus"]
    label: str
    desired_enabled: bool
    effective_enabled: bool
    suppressed_by: tuple[str, ...]
    resume_condition: str
    status_text: str
    detail: str


@dataclass(frozen=True, slots=True)
class StatusPresentation:
    """Comparable text projection used by all low-frequency status surfaces."""

    headline: str
    detail: str
    next_break_text: str
    pause_text: str
    resume_condition: str
    filter: FeatureStatusPresentation
    dimmer: FeatureStatusPresentation
    breaks: FeatureStatusPresentation
    focus: FeatureStatusPresentation

    @property
    def effects(self) -> tuple[FeatureStatusPresentation, ...]:
        """Return the four effect rows in their canonical display order."""

        return (self.filter, self.dimmer, self.breaks, self.focus)


_MISSING = object()

_FEATURE_LABELS = {
    "filter": "色温",
    "dimmer": "调暗",
    "breaks": "休息提醒",
    "focus": "专注遮罩",
}

_SUPPRESSION_LABELS = {
    "global_pause": "全局暂停",
    "fullscreen": "全屏应用",
    "presentation": "演示模式",
    "d3d_fullscreen": "全屏游戏",
    "app_rule": "应用规则",
    "idle": "暂时离开电脑",
    "natural_rest": "自然休息",
    "locked": "锁屏",
    "session_locked": "锁屏",
    "suspended": "系统睡眠",
    "system_suspended": "系统睡眠",
    "hdr_active": "HDR",
}


def _read(value: object, path: str, default: Any = None) -> Any:
    """Read a dotted path from dataclasses, mappings or compatible objects."""

    current: Any = value
    for name in path.split("."):
        if current is None:
            return default
        if isinstance(current, Mapping):
            current = current.get(name, _MISSING)
        else:
            current = getattr(current, name, _MISSING)
        if current is _MISSING:
            return default
    return current


def _unique_reasons(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        values = (value,)
    else:
        try:
            values = tuple(value)  # type: ignore[arg-type]
        except TypeError:
            return ()
    return tuple(dict.fromkeys(str(item) for item in values if str(item)))


def _reason_label(reason: str) -> str:
    if reason.startswith("app:"):
        app_id = reason.removeprefix("app:")
        return f"应用 {app_id}" if app_id else "应用规则"
    return _SUPPRESSION_LABELS.get(reason, "当前情境")


def _reason_text(reasons: tuple[str, ...]) -> str:
    return "、".join(_reason_label(reason) for reason in reasons)


def _inferred_resume_condition(reasons: tuple[str, ...]) -> str:
    reason_set = set(reasons)
    if reason_set & {"locked", "session_locked"}:
        return "解锁后自动恢复"
    if reason_set & {"suspended", "system_suspended"}:
        return "唤醒电脑后自动恢复"
    if "global_pause" in reason_set:
        return "手动恢复后继续"
    if reason_set & {"fullscreen", "presentation", "d3d_fullscreen"}:
        return "退出全屏或演示后自动恢复"
    if reason_set & {"idle", "natural_rest"}:
        return "检测到继续使用后自动恢复"
    if "hdr_active" in reason_set:
        return "关闭 HDR 后重新检测"
    if "app_rule" in reason_set or any(
        reason.startswith("app:") for reason in reasons
    ):
        return "切换离开该应用后自动恢复"
    if reasons:
        return "当前情境结束后自动恢复"
    return ""


def _format_duration(seconds: object) -> str:
    try:
        value = max(0, int(seconds))
    except (TypeError, ValueError):
        return "--"
    if value >= 3600:
        hours, remainder = divmod(value, 3600)
        minutes = remainder // 60
        return f"{hours} 小时 {minutes} 分" if minutes else f"{hours} 小时"
    minutes, secs = divmod(value, 60)
    return f"{minutes}:{secs:02d}"


class StatusPresenter:
    """Project :class:`AppState` into user-facing, species-neutral status."""

    @classmethod
    def project(cls, state: AppState) -> StatusPresentation:
        global_pause = bool(_read(state, "global_pause.active", False))
        pause_text, pause_resume = cls._global_pause_copy(state, global_pause)

        filter_status = cls._feature_status(state, "filter")
        dimmer_status = cls._feature_status(state, "dimmer")
        breaks_status = cls._feature_status(state, "breaks")
        focus_status = cls._feature_status(state, "focus")
        effects = (filter_status, dimmer_status, breaks_status, focus_status)

        resume_condition = pause_resume or next(
            (item.resume_condition for item in effects if item.resume_condition),
            "",
        )
        next_break_text = cls._next_break_text(
            state,
            breaks_status,
            global_pause=global_pause,
        )
        headline, detail = cls._companion_copy(
            state,
            breaks_status=breaks_status,
            global_pause=global_pause,
            pause_text=pause_text,
            next_break_text=next_break_text,
        )
        return StatusPresentation(
            headline=headline,
            detail=detail,
            next_break_text=next_break_text,
            pause_text=pause_text,
            resume_condition=resume_condition,
            filter=filter_status,
            dimmer=dimmer_status,
            breaks=breaks_status,
            focus=focus_status,
        )

    @staticmethod
    def _legacy_desired(state: object, feature_id: str) -> bool:
        path = {
            "filter": "display.filter_enabled",
            "dimmer": "display.dimmer_enabled",
            "breaks": "breaks.enabled",
            "focus": "focus.enabled",
        }[feature_id]
        return bool(_read(state, path, False))

    @classmethod
    def _feature_status(
        cls,
        state: object,
        feature_id: Literal["filter", "dimmer", "breaks", "focus"],
    ) -> FeatureStatusPresentation:
        runtime = _read(state, f"effective_policy.{feature_id}", None)
        desired_value = _read(runtime, "desired_enabled", _MISSING)
        desired = (
            cls._legacy_desired(state, feature_id)
            if desired_value is _MISSING
            else bool(desired_value)
        )
        effective_value = _read(runtime, "effective_enabled", _MISSING)
        effective = desired if effective_value is _MISSING else bool(effective_value)
        reasons = _unique_reasons(_read(runtime, "suppressed_by", ()))
        resume = str(_read(runtime, "resume_condition", "") or "")

        health_status = str(_read(state, "display_health.status", "") or "")
        health_message = str(_read(state, "display_health.message", "") or "")
        health_pending = bool(_read(state, "display_health.pending", False))
        hdr_active = bool(_read(state, "display_health.hdr_active", False))
        if feature_id == "filter" and desired and hdr_active:
            reasons = _unique_reasons((*reasons, "hdr_active"))
            effective = False
        if reasons and not resume:
            resume = _inferred_resume_condition(reasons)

        preference_text = "开启" if desired else "关闭"
        if not desired:
            status_text = "未开启"
            actual_text = "未运行"
        elif effective:
            status_text = "实际生效"
            actual_text = "正在运行"
        elif reasons:
            status_text = "已开启，当前暂停"
            actual_text = f"因{_reason_text(reasons)}暂停"
        elif feature_id in {"filter", "dimmer"} and health_pending:
            status_text = "正在应用"
            actual_text = "等待系统确认"
        elif feature_id in {"filter", "dimmer"} and health_status in {
            "error",
            "degraded",
            "unavailable",
        }:
            status_text = "应用失败" if health_status == "error" else "暂不可用"
            actual_text = health_message or "系统未确认效果"
        else:
            status_text = "已开启，尚未生效"
            actual_text = "尚未运行"

        detail = f"用户偏好：{preference_text}；实际效果：{actual_text}"
        if resume:
            detail = f"{detail}；{resume}"
        return FeatureStatusPresentation(
            feature_id=feature_id,
            label=_FEATURE_LABELS[feature_id],
            desired_enabled=desired,
            effective_enabled=effective,
            suppressed_by=reasons,
            resume_condition=resume,
            status_text=status_text,
            detail=detail,
        )

    @staticmethod
    def _global_pause_copy(state: object, active: bool) -> tuple[str, str]:
        if not active:
            return "", ""
        mode = str(_read(state, "global_pause.mode", "none") or "none")
        until = _read(state, "global_pause.until", None)
        if isinstance(until, datetime):
            local_until = until.astimezone().strftime("%H:%M")
            resume = f"{local_until} 自动恢复"
        elif mode == "next_schedule":
            resume = "下一次自动切换时恢复"
        elif mode == "timed":
            resume = "暂停时间结束后自动恢复"
        else:
            resume = "等待手动恢复"
        return f"全局暂停中，{resume}", resume

    @staticmethod
    def _next_break_text(
        state: object,
        status: FeatureStatusPresentation,
        *,
        global_pause: bool,
    ) -> str:
        phase = str(_read(state, "breaks.phase", "stopped") or "stopped")
        remaining = _read(state, "break_cadence.short_remaining", _MISSING)
        if remaining is _MISSING or (
            not remaining and _read(state, "breaks.remaining", 0)
        ):
            remaining = _read(state, "breaks.remaining", 0)
        if not status.desired_enabled:
            return "休息提醒未开启"
        if phase == "resting":
            return f"本次休息剩余 {_format_duration(remaining)}"
        if phase == "prompting":
            return "该休息一下了"
        if global_pause:
            return "休息计时已暂停 · 恢复后继续"
        if status.suppressed_by:
            suffix = status.resume_condition or "当前情境结束后自动恢复"
            return f"休息计时已暂停 · {suffix}"
        if bool(_read(state, "breaks.paused", False)):
            return "休息计时已暂停"
        if int(remaining or 0) <= 0:
            return "正在准备下一次休息"
        return f"距离下次休息 {_format_duration(remaining)}"

    @staticmethod
    def _companion_copy(
        state: object,
        *,
        breaks_status: FeatureStatusPresentation,
        global_pause: bool,
        pause_text: str,
        next_break_text: str,
    ) -> tuple[str, str]:
        phase = str(_read(state, "breaks.phase", "stopped") or "stopped")
        companion_enabled = bool(_read(state, "companion.enabled", True))
        companion_visible = bool(_read(state, "companion.visible", True))
        companion_reasons = _unique_reasons(
            _read(state, "companion.suppressed_by", ())
        )

        if phase == "resting":
            return "休息进行中", "放下手头工作，和伙伴一起看看远处。"
        if phase == "prompting":
            return "该休息一下了", "伙伴在等你完成一次短暂休息。"
        if global_pause:
            return "陪伴已暂停", pause_text
        if companion_reasons:
            resume = _inferred_resume_condition(companion_reasons)
            return "伙伴暂时安静", f"因{_reason_text(companion_reasons)}隐藏；{resume}"
        if breaks_status.suppressed_by:
            return "伙伴正在安静陪伴", breaks_status.detail
        if not companion_enabled:
            return "桌面伙伴未开启", "可以随时从托盘或伙伴小屋重新开启。"
        if not companion_visible:
            return "伙伴在托盘等你", "显示桌面伙伴后即可继续互动。"
        return "伙伴正在陪伴你", next_break_text
