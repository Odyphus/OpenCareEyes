"""Pure context-to-suppression policy."""

from __future__ import annotations

from collections.abc import Iterable

from opencareyes.domain.context import (
    AppRule,
    AutoPausePreferences,
    ContextSnapshot,
    FeatureSuppression,
    SuppressionDecision,
)


class AutoPausePolicy:
    """Evaluate context without mutating preferences or effect services."""

    IDLE_PAUSE_SECONDS = 2 * 60
    NATURAL_REST_SECONDS = 5 * 60

    @classmethod
    def evaluate(
        cls,
        snapshot: ContextSnapshot,
        preferences: AutoPausePreferences,
        app_rules: Iterable[AppRule],
        manual_break_override: bool = False,
    ) -> SuppressionDecision:
        reasons: dict[str, list[str]] = {
            "filter": [],
            "dimmer": [],
            "breaks": [],
            "focus": [],
        }
        conditions: dict[str, list[str]] = {feature: [] for feature in reasons}

        def suppress(feature: str, reason: str, condition: str) -> None:
            if reason not in reasons[feature]:
                reasons[feature].append(reason)
                conditions[feature].append(condition)

        safety_reason = ""
        if snapshot.session == "suspended":
            safety_reason = "system_suspended"
            safety_condition = "resume_system"
        elif snapshot.session == "locked":
            safety_reason = "session_locked"
            safety_condition = "unlock_session"
        else:
            safety_condition = ""

        if safety_reason:
            suppress("breaks", safety_reason, safety_condition)
            suppress("focus", safety_reason, safety_condition)

        natural_rest = (
            preferences.natural_rest_enabled
            and snapshot.session in {"locked", "suspended"}
            and snapshot.idle_seconds >= cls.NATURAL_REST_SECONDS
        )
        if preferences.smart_pause_enabled and snapshot.session == "active":
            fullscreen_reason = cls._fullscreen_reason(snapshot)
            if preferences.fullscreen_pause_enabled and fullscreen_reason:
                if not manual_break_override:
                    suppress("breaks", fullscreen_reason, "leave_fullscreen_context")
                suppress("focus", fullscreen_reason, "leave_fullscreen_context")

            matching_rule = next(
                (rule for rule in app_rules if rule.app_id == snapshot.foreground_app_id),
                None,
            )
            if matching_rule is not None:
                app_reason = f"app:{matching_rule.app_id}"
                for feature in ("filter", "dimmer", "breaks", "focus"):
                    if getattr(matching_rule, feature) and not (
                        feature == "breaks" and manual_break_override
                    ):
                        suppress(feature, app_reason, "leave_application")

            if snapshot.idle_seconds >= cls.IDLE_PAUSE_SECONDS:
                if not manual_break_override:
                    suppress("breaks", "idle", "user_returns")
                if (
                    preferences.natural_rest_enabled
                    and snapshot.idle_seconds >= cls.NATURAL_REST_SECONDS
                ):
                    natural_rest = not manual_break_override
                    suppress("focus", "natural_rest", "user_returns")

        return SuppressionDecision(
            filter=cls._result(reasons["filter"], conditions["filter"]),
            dimmer=cls._result(reasons["dimmer"], conditions["dimmer"]),
            breaks=cls._result(reasons["breaks"], conditions["breaks"]),
            focus=cls._result(reasons["focus"], conditions["focus"]),
            natural_rest=natural_rest,
        )

    @staticmethod
    def _fullscreen_reason(snapshot: ContextSnapshot) -> str:
        if snapshot.notification_mode == "d3d_fullscreen":
            return "d3d_fullscreen"
        if snapshot.notification_mode == "presentation":
            return "presentation"
        if snapshot.fullscreen or snapshot.notification_mode == "busy":
            return "fullscreen"
        return ""

    @staticmethod
    def _result(reasons: list[str], conditions: list[str]) -> FeatureSuppression:
        if not reasons:
            return FeatureSuppression()
        unique_conditions = tuple(dict.fromkeys(conditions))
        resume_condition = (
            unique_conditions[0]
            if len(unique_conditions) == 1
            else "all_suppressions_clear"
        )
        return FeatureSuppression(tuple(reasons), resume_condition)
