"""Apply temporary context suppression without changing user preferences."""

from __future__ import annotations

import logging
import time

from PySide6.QtCore import QObject, Signal

from opencareyes.domain.context import SuppressionDecision
from opencareyes.state import EffectivePolicyState, FeatureRuntimeState

log = logging.getLogger(__name__)

_RESUME_TEXT = {
    "leave_fullscreen_context": "退出全屏后 2 秒恢复",
    "leave_application": "离开该应用后 2 秒恢复",
    "user_returns": "返回电脑后恢复",
    "unlock_session": "解锁后恢复",
    "resume_system": "系统唤醒后恢复",
    "all_suppressions_clear": "所有免打扰原因结束后恢复",
}


class EffectCoordinator(QObject):
    """Coordinate desired/effective state and compensate failed transitions."""

    state_changed = Signal(object)
    operation_failed = Signal(str, str)

    def __init__(
        self,
        settings,
        *,
        blue_filter=None,
        dimmer=None,
        break_reminder=None,
        focus_mode=None,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self._settings = settings
        self._blue_filter = blue_filter
        self._dimmer = dimmer
        self._break_reminder = break_reminder
        self._focus_mode = focus_mode
        self._decision = SuppressionDecision()
        self._last_apply_succeeded = True
        self._auto_paused_breaks = False
        self._natural_rest_pending = False
        self._state = self._build_state()

    @property
    def state(self) -> EffectivePolicyState:
        return self._state

    @property
    def last_apply_succeeded(self) -> bool:
        return self._last_apply_succeeded

    def apply(self, decision: SuppressionDecision) -> EffectivePolicyState:
        if self._is_globally_paused():
            self._decision = decision
            self._last_apply_succeeded = True
            return self._publish_state()

        before = self._capture_before_state()
        try:
            self._apply_display_feature(
                "filter",
                self._blue_filter,
                bool(self._settings.filter_enabled),
                decision.filter.suppressed,
                lambda: self._blue_filter.enable(
                    self._settings.color_temperature
                ),
            )
            self._apply_display_feature(
                "dimmer",
                self._dimmer,
                bool(self._settings.dimmer_enabled),
                decision.dimmer.suppressed,
                lambda: self._dimmer.enable(self._settings.dim_level),
            )
            self._apply_display_feature(
                "focus",
                self._focus_mode,
                bool(self._settings.focus_enabled),
                decision.focus.suppressed,
                self._focus_mode.enable if self._focus_mode is not None else None,
            )
            self._apply_breaks(decision)
        except Exception as exc:
            self._last_apply_succeeded = False
            log.exception("Context effect transition failed")
            self.operation_failed.emit("context_effect", str(exc))
            self._restore_before_state(before)
        else:
            self._decision = decision
            self._last_apply_succeeded = True
        return self._publish_state()

    def refresh(self) -> EffectivePolicyState:
        """Re-project actual service state without changing suppression."""

        return self._publish_state()

    def _apply_display_feature(
        self,
        name: str,
        service,
        desired: bool,
        suppressed: bool,
        enable,
    ) -> None:
        if service is None:
            if desired and not suppressed:
                raise RuntimeError(f"{name} service is unavailable")
            return
        actual = bool(getattr(service, "enabled", False))
        target = desired and not suppressed
        if target == actual:
            return
        if target:
            if enable is None:
                raise RuntimeError(f"{name} cannot be enabled")
            result = enable()
            if result is False or not bool(getattr(service, "enabled", True)):
                raise RuntimeError(f"{name} did not enter the enabled state")
        else:
            result = service.disable()
            if result is False or bool(getattr(service, "enabled", False)):
                raise RuntimeError(f"{name} did not enter the disabled state")

    def _apply_breaks(self, decision: SuppressionDecision) -> None:
        reminder = self._break_reminder
        if decision.natural_rest:
            self._natural_rest_pending = True
        if reminder is None:
            if self._settings.break_enabled and not decision.breaks.suppressed:
                raise RuntimeError("break reminder service is unavailable")
            return
        if not self._settings.break_enabled:
            self._auto_paused_breaks = False
            self._natural_rest_pending = False
            return
        if decision.breaks.suppressed:
            if reminder.enabled and not reminder.paused:
                reminder.pause()
                self._auto_paused_breaks = True
            return
        if self._natural_rest_pending:
            reminder.start()
            self._natural_rest_pending = False
            self._auto_paused_breaks = False
        elif self._auto_paused_breaks and reminder.enabled and reminder.paused:
            reminder.resume()
            self._auto_paused_breaks = False

    def _capture_before_state(self) -> dict[str, object]:
        reminder = self._break_reminder
        return {
            "filter": bool(getattr(self._blue_filter, "enabled", False)),
            "dimmer": bool(getattr(self._dimmer, "enabled", False)),
            "focus": bool(getattr(self._focus_mode, "enabled", False)),
            "break_enabled": bool(getattr(reminder, "enabled", False)),
            "break_paused": bool(getattr(reminder, "paused", False)),
            "auto_paused": self._auto_paused_breaks,
            "natural_rest": self._natural_rest_pending,
        }

    def _restore_before_state(self, before: dict[str, object]) -> None:
        failures = []
        for name, service, enabled, enable in (
            (
                "filter",
                self._blue_filter,
                before["filter"],
                lambda: self._blue_filter.enable(self._settings.color_temperature),
            ),
            (
                "dimmer",
                self._dimmer,
                before["dimmer"],
                lambda: self._dimmer.enable(self._settings.dim_level),
            ),
            (
                "focus",
                self._focus_mode,
                before["focus"],
                self._focus_mode.enable if self._focus_mode is not None else None,
            ),
        ):
            if service is None:
                continue
            try:
                if enabled and enable is not None:
                    result = enable()
                elif not enabled:
                    result = service.disable()
                else:
                    result = None
                if result is False or bool(getattr(service, "enabled", False)) != bool(
                    enabled
                ):
                    raise RuntimeError("state verification failed")
            except Exception as exc:  # pragma: no cover - fault injection covers signal
                failures.append(f"{name}: {exc}")

        reminder = self._break_reminder
        if reminder is not None:
            try:
                if not before["break_enabled"]:
                    reminder.stop()
                else:
                    if not reminder.enabled:
                        reminder.start()
                    if before["break_paused"] and not reminder.paused:
                        reminder.pause()
                    elif not before["break_paused"] and reminder.paused:
                        reminder.resume()
                    if (
                        bool(reminder.enabled) != bool(before["break_enabled"])
                        or bool(reminder.paused) != bool(before["break_paused"])
                    ):
                        raise RuntimeError("state verification failed")
            except Exception as exc:  # pragma: no cover - fault injection covers signal
                failures.append(f"breaks: {exc}")
        self._auto_paused_breaks = bool(before["auto_paused"])
        self._natural_rest_pending = bool(before["natural_rest"])
        if failures:
            self.operation_failed.emit(
                "context_compensation",
                "; ".join(failures),
            )

    def _publish_state(self) -> EffectivePolicyState:
        state = self._build_state()
        if state != self._state:
            self._state = state
            self.state_changed.emit(state)
        return self._state

    def _build_state(self) -> EffectivePolicyState:
        decision = self._decision
        global_reason = ("global_pause",) if self._is_globally_paused() else ()

        def feature(name: str, desired: bool, service, suppression) -> FeatureRuntimeState:
            reasons = global_reason + self._normalise_reasons(
                suppression.suppressed_by
            )
            actual = bool(getattr(service, "enabled", False))
            if name == "breaks":
                actual = actual and not bool(getattr(service, "paused", False))
            return FeatureRuntimeState(
                desired_enabled=desired,
                effective_enabled=actual and not reasons,
                suppressed_by=tuple(dict.fromkeys(reasons)),
                resume_condition=(
                    "等待手动恢复"
                    if global_reason
                    else _RESUME_TEXT.get(
                        suppression.resume_condition,
                        suppression.resume_condition,
                    )
                ),
            )

        return EffectivePolicyState(
            filter=feature(
                "filter",
                bool(self._settings.filter_enabled),
                self._blue_filter,
                decision.filter,
            ),
            dimmer=feature(
                "dimmer",
                bool(self._settings.dimmer_enabled),
                self._dimmer,
                decision.dimmer,
            ),
            breaks=feature(
                "breaks",
                bool(self._settings.break_enabled),
                self._break_reminder,
                decision.breaks,
            ),
            focus=feature(
                "focus",
                bool(self._settings.focus_enabled),
                self._focus_mode,
                decision.focus,
            ),
        )

    @staticmethod
    def _normalise_reasons(reasons: tuple[str, ...]) -> tuple[str, ...]:
        result = []
        for reason in reasons:
            if reason == "session_locked":
                reason = "locked"
            elif reason == "system_suspended":
                reason = "suspended"
            elif reason == "natural_rest":
                reason = "idle"
            elif reason.startswith("app:"):
                reason = "app_rule"
            if reason not in result:
                result.append(reason)
        return tuple(result)

    def _is_globally_paused(self) -> bool:
        mode = self._settings.global_pause_mode
        if mode != "timed":
            return mode in {"manual", "next_schedule"}
        until = self._settings.global_pause_until
        return until is not None and until > time.time()
