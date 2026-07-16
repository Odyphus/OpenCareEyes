from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import datetime
from types import SimpleNamespace

import pytest

from opencareyes.application.status_presenter import StatusPresenter
from opencareyes.state import (
    AppState,
    BreakCadenceState,
    BreakState,
    DisplayHealthState,
    DisplayState,
    EffectivePolicyState,
    FeatureRuntimeState,
    GlobalPauseState,
)


def _runtime(
    desired: bool = False,
    effective: bool = False,
    reasons: tuple[str, ...] = (),
    resume: str = "",
) -> FeatureRuntimeState:
    return FeatureRuntimeState(
        desired_enabled=desired,
        effective_enabled=effective,
        suppressed_by=reasons,
        resume_condition=resume,
    )


def _state(**changes) -> AppState:
    state = AppState(
        display=DisplayState(filter_enabled=True, color_temperature=4200),
        breaks=BreakState(
            enabled=True,
            phase="working",
            remaining=1200,
            total=1200,
        ),
        break_cadence=BreakCadenceState(short_remaining=1200),
        effective_policy=EffectivePolicyState(
            filter=_runtime(True, True),
            breaks=_runtime(True, True),
        ),
        display_health=DisplayHealthState(status="ok"),
    )
    return replace(state, **changes)


def test_projects_normal_companion_and_four_explicit_effect_rows():
    projected = StatusPresenter.project(_state())

    assert projected.headline == "伙伴正在陪伴你"
    assert projected.next_break_text == "距离下次休息 20:00"
    assert [item.feature_id for item in projected.effects] == [
        "filter",
        "dimmer",
        "breaks",
        "focus",
    ]
    assert projected.filter.desired_enabled is True
    assert projected.filter.effective_enabled is True
    assert projected.filter.status_text == "实际生效"
    assert "用户偏好：开启" in projected.filter.detail
    assert "实际效果：正在运行" in projected.filter.detail

    assert StatusPresenter.project(_state()) == projected
    with pytest.raises(FrozenInstanceError):
        projected.headline = "不可修改"  # type: ignore[misc]


def test_projects_fullscreen_suppression_and_resume_condition():
    state = _state(
        effective_policy=EffectivePolicyState(
            filter=_runtime(True, True),
            breaks=_runtime(
                True,
                False,
                ("fullscreen",),
                "退出全屏后恢复",
            ),
        )
    )

    projected = StatusPresenter.project(state)

    assert projected.headline == "伙伴正在安静陪伴"
    assert projected.breaks.status_text == "已开启，当前暂停"
    assert projected.breaks.suppressed_by == ("fullscreen",)
    assert projected.breaks.resume_condition == "退出全屏后恢复"
    assert "因全屏应用暂停" in projected.breaks.detail
    assert projected.next_break_text == "休息计时已暂停 · 退出全屏后恢复"
    assert projected.resume_condition == "退出全屏后恢复"


def test_projects_global_pause_without_losing_user_preferences():
    state = _state(
        global_pause=GlobalPauseState(
            active=True,
            mode="timed",
            until=datetime(2026, 7, 16, 21, 30),
        ),
        effective_policy=EffectivePolicyState(
            filter=_runtime(True, False, ("global_pause",)),
            breaks=_runtime(True, False, ("global_pause",)),
        ),
    )

    projected = StatusPresenter.project(state)

    assert projected.headline == "陪伴已暂停"
    assert projected.pause_text == "全局暂停中，21:30 自动恢复"
    assert projected.resume_condition == "21:30 自动恢复"
    assert projected.filter.desired_enabled is True
    assert projected.filter.effective_enabled is False
    assert projected.filter.suppressed_by == ("global_pause",)
    assert "用户偏好：开启" in projected.filter.detail
    assert projected.next_break_text == "休息计时已暂停 · 恢复后继续"


@pytest.mark.parametrize(
    ("health", "expected_status", "expected_detail"),
    [
        (
            DisplayHealthState(
                status="suppressed",
                hdr_active=True,
                message="HDR 已开启",
            ),
            "已开启，当前暂停",
            "关闭 HDR 后重新检测",
        ),
        (
            DisplayHealthState(status="error", message="Gamma Ramp 应用失败"),
            "应用失败",
            "Gamma Ramp 应用失败",
        ),
    ],
)
def test_projects_hdr_and_display_failure_as_text(
    health: DisplayHealthState,
    expected_status: str,
    expected_detail: str,
):
    state = _state(
        effective_policy=EffectivePolicyState(
            filter=_runtime(True, False),
            breaks=_runtime(True, True),
        ),
        display_health=health,
    )

    projected = StatusPresenter.project(state)

    assert projected.filter.status_text == expected_status
    assert expected_detail in projected.filter.detail
    assert projected.filter.desired_enabled is True
    assert projected.filter.effective_enabled is False


def test_projects_active_rest_and_is_robust_to_compatible_missing_state():
    resting = _state(
        breaks=BreakState(
            enabled=True,
            phase="resting",
            remaining=18,
            total=20,
        ),
        break_cadence=BreakCadenceState(short_remaining=18),
    )

    projected = StatusPresenter.project(resting)

    assert projected.headline == "休息进行中"
    assert projected.next_break_text == "本次休息剩余 0:18"
    assert "看看远处" in projected.detail

    compatible = StatusPresenter.project(SimpleNamespace())
    assert compatible.headline == "伙伴正在陪伴你"
    assert compatible.next_break_text == "休息提醒未开启"
    assert all(not effect.desired_enabled for effect in compatible.effects)
