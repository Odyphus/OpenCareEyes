"""Pure tests for context values and auto-pause policy."""

from dataclasses import FrozenInstanceError

import pytest

from opencareyes.domain.context import (
    AppRule,
    AutoPausePreferences,
    ContextSnapshot,
)
from opencareyes.domain.policy import AutoPausePolicy


def evaluate(
    snapshot: ContextSnapshot,
    *,
    preferences: AutoPausePreferences | None = None,
    rules: tuple[AppRule, ...] = (),
    override: bool = False,
):
    return AutoPausePolicy.evaluate(
        snapshot,
        preferences or AutoPausePreferences(),
        rules,
        manual_break_override=override,
    )


def test_app_rule_normalises_basename_and_is_immutable():
    rule = AppRule("  PowerPnt.EXE ")

    assert rule.app_id == "powerpnt.exe"
    with pytest.raises(FrozenInstanceError):
        rule.breaks = False


@pytest.mark.parametrize(
    "app_id",
    ["", "C:\\Apps\\game.exe", "folder/game.exe", "c:game.exe", "readme", "x" * 129],
)
def test_app_rule_rejects_identifiers_that_could_persist_a_path(app_id):
    with pytest.raises(ValueError):
        AppRule(app_id)


def test_fullscreen_pauses_breaks_and_focus_but_not_display_effects():
    decision = evaluate(
        ContextSnapshot(
            foreground_app_id="chrome.exe",
            fullscreen=True,
            notification_mode="normal",
        )
    )

    assert decision.breaks.suppressed_by == ("fullscreen",)
    assert decision.focus.suppressed_by == ("fullscreen",)
    assert not decision.filter.suppressed
    assert not decision.dimmer.suppressed


@pytest.mark.parametrize(
    ("mode", "reason"),
    [("busy", "fullscreen"), ("presentation", "presentation"), ("d3d_fullscreen", "d3d_fullscreen")],
)
def test_notification_modes_have_stable_reason_codes(mode, reason):
    decision = evaluate(ContextSnapshot(notification_mode=mode))

    assert decision.breaks.suppressed_by == (reason,)
    assert decision.focus.suppressed_by == (reason,)


def test_fullscreen_setting_only_disables_fullscreen_suppression():
    preferences = AutoPausePreferences(fullscreen_pause_enabled=False)
    rule = AppRule("reader.exe", filter=True)
    decision = evaluate(
        ContextSnapshot(
            foreground_app_id="reader.exe",
            fullscreen=True,
            notification_mode="presentation",
        ),
        preferences=preferences,
        rules=(rule,),
    )

    assert decision.breaks.suppressed_by == ("app:reader.exe",)
    assert decision.filter.suppressed_by == ("app:reader.exe",)


def test_application_rule_can_suppress_each_selected_effect():
    rule = AppRule(
        "game.exe",
        breaks=True,
        focus=False,
        filter=True,
        dimmer=True,
    )
    decision = evaluate(
        ContextSnapshot(foreground_app_id="game.exe", notification_mode="normal"),
        rules=(rule,),
    )

    assert decision.breaks.suppressed
    assert not decision.focus.suppressed
    assert decision.filter.suppressed
    assert decision.dimmer.suppressed


def test_idle_pause_and_natural_rest_have_separate_thresholds():
    short_idle = evaluate(ContextSnapshot(idle_seconds=120, notification_mode="normal"))
    long_idle = evaluate(ContextSnapshot(idle_seconds=300, notification_mode="normal"))

    assert short_idle.breaks.suppressed_by == ("idle",)
    assert not short_idle.natural_rest
    assert not short_idle.focus.suppressed
    assert long_idle.natural_rest
    assert long_idle.focus.suppressed_by == ("natural_rest",)


def test_manual_break_override_only_clears_non_safety_break_reasons():
    decision = evaluate(
        ContextSnapshot(
            foreground_app_id="game.exe",
            fullscreen=True,
            notification_mode="normal",
            idle_seconds=400,
        ),
        rules=(AppRule("game.exe"),),
        override=True,
    )

    assert not decision.breaks.suppressed
    assert decision.focus.suppressed
    assert not decision.natural_rest


@pytest.mark.parametrize(("session", "reason"), [("locked", "session_locked"), ("suspended", "system_suspended")])
def test_session_safety_suppression_cannot_be_disabled_or_overridden(session, reason):
    preferences = AutoPausePreferences(
        smart_pause_enabled=False,
        fullscreen_pause_enabled=False,
        natural_rest_enabled=True,
    )
    decision = evaluate(
        ContextSnapshot(session=session, idle_seconds=300),
        preferences=preferences,
        override=True,
    )

    assert decision.breaks.suppressed_by == (reason,)
    assert decision.focus.suppressed_by == (reason,)
    assert decision.natural_rest


def test_multiple_reasons_are_deduplicated_and_require_all_to_clear():
    decision = evaluate(
        ContextSnapshot(
            foreground_app_id="game.exe",
            fullscreen=True,
            notification_mode="normal",
            idle_seconds=120,
        ),
        rules=(AppRule("game.exe"), AppRule("game.exe")),
    )

    assert decision.breaks.suppressed_by == ("fullscreen", "app:game.exe", "idle")
    assert decision.breaks.resume_condition == "all_suppressions_clear"


def test_smart_pause_switch_keeps_activity_weighted_idle_freeze():
    decision = evaluate(
        ContextSnapshot(
            foreground_app_id="game.exe",
            fullscreen=True,
            notification_mode="d3d_fullscreen",
            idle_seconds=1000,
        ),
        preferences=AutoPausePreferences(smart_pause_enabled=False),
        rules=(AppRule("game.exe", filter=True, dimmer=True),),
    )

    assert decision.breaks.suppressed_by == ("idle",)
    assert decision.focus.suppressed_by == ("natural_rest",)
    assert not decision.filter.suppressed
    assert not decision.dimmer.suppressed
    assert decision.natural_rest


def test_idle_over_five_minutes_still_freezes_when_natural_rest_is_off():
    decision = evaluate(
        ContextSnapshot(idle_seconds=1000, notification_mode="normal"),
        preferences=AutoPausePreferences(
            smart_pause_enabled=False,
            natural_rest_enabled=False,
        ),
    )

    assert decision.breaks.suppressed_by == ("idle",)
    assert not decision.focus.suppressed
    assert not decision.natural_rest
