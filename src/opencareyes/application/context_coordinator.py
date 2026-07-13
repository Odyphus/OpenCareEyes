"""Debounce context snapshots and publish effective application state."""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QTimer, Signal

from opencareyes.domain.context import (
    AppRule,
    AutoPausePreferences,
    ContextSnapshot,
    SuppressionDecision,
)
from opencareyes.domain.policy import AutoPausePolicy
from opencareyes.domain.runtime import DesiredEffectState
from opencareyes.state import ContextState

log = logging.getLogger(__name__)


class ContextCoordinator(QObject):
    """Own context debounce and manual overrides outside AppController."""

    runtime_changed = Signal(object, object)
    reconcile_completed = Signal(object)
    operation_failed = Signal(str, str)

    ENTER_DELAY_MS = 500
    EXIT_DELAY_MS = 2000

    def __init__(
        self,
        settings,
        sensor,
        effects,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self._settings = settings
        self._sensor = sensor
        self._effects = effects
        self._policy = AutoPausePolicy()
        self._snapshot = sensor.current_snapshot
        self._recent_app_id = ""
        self._applied_decision = SuppressionDecision()
        self._pending_decision = None
        self._pending_snapshot = None
        self._pending_report_failure = False
        self._manual_break_override = False
        self._override_key = None
        self._availability_error_reported = False
        self._last_published_signature = None
        self._desired_override: DesiredEffectState | None = None
        self._global_pause_override: bool | None = None
        self._display_revision = 0
        self._display_purpose = "system"
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._apply_pending)
        sensor.snapshot_changed.connect(self._on_snapshot)
        sensor.availability_changed.connect(self._on_availability)
        self._last_result = getattr(effects, "last_result", None)

    @property
    def context_state(self) -> ContextState:
        return self._to_context_state(self._snapshot)

    @property
    def effective_policy(self):
        return self._effects.state

    @property
    def effects(self):
        """Expose the shared effect boundary for controller wiring."""

        return self._effects

    @property
    def last_result(self):
        return self._last_result

    def start(self) -> None:
        self._sensor.start()
        self.recompute()

    def stop(self) -> None:
        self._timer.stop()
        self._sensor.stop()

    def recompute(
        self,
        preview=None,
        *,
        desired: DesiredEffectState | None = None,
        global_pause: bool | None = None,
        display_revision: int | None = None,
        display_purpose: str | None = None,
        force_display_commit: bool = False,
    ) -> None:
        """Apply preference changes immediately against the latest snapshot."""

        if desired is not None:
            self._desired_override = desired
        if global_pause is not None:
            self._global_pause_override = bool(global_pause)
        if display_revision is not None:
            self._display_revision = max(0, int(display_revision))
        if display_purpose is not None:
            self._display_purpose = str(display_purpose)

        self._evaluate(
            self._sensor.current_snapshot,
            immediate=True,
            preview=preview,
            report_failure=False,
            force_display_commit=force_display_commit,
        )

    def clear_runtime_override(self) -> None:
        self._desired_override = None
        self._global_pause_override = None
        self._display_revision = 0
        self._display_purpose = "system"

    def clear_display_override(self) -> None:
        """Compatibility alias for the v0.3 display-only override."""

        self.clear_runtime_override()

    def resume_breaks_for_current_context(self) -> bool:
        self._manual_break_override = True
        self._override_key = self._context_key(self._sensor.current_snapshot)
        self.recompute()
        return bool(getattr(self._last_result, "succeeded", True))

    def _on_snapshot(self, snapshot: ContextSnapshot) -> None:
        key = self._context_key(snapshot)
        if self._manual_break_override and key != self._override_key:
            self._manual_break_override = False
            self._override_key = None
        self._evaluate(snapshot, immediate=False, report_failure=True)

    def _evaluate(
        self,
        snapshot: ContextSnapshot,
        *,
        immediate: bool,
        preview=None,
        report_failure: bool = False,
        force_display_commit: bool = False,
    ) -> None:
        self._snapshot = snapshot
        if snapshot.foreground_app_id:
            self._recent_app_id = snapshot.foreground_app_id
        decision = self._policy.evaluate(
            snapshot,
            AutoPausePreferences(
                smart_pause_enabled=bool(self._settings.smart_pause_enabled),
                fullscreen_pause_enabled=bool(
                    self._settings.fullscreen_pause_enabled
                ),
                natural_rest_enabled=bool(self._settings.natural_rest_enabled),
            ),
            self._app_rules(),
            manual_break_override=self._manual_break_override,
        )
        if decision == self._applied_decision:
            self._timer.stop()
            self._pending_decision = None
            self._pending_snapshot = None
            self._pending_report_failure = False
            if immediate:
                self._apply(
                    snapshot,
                    decision,
                    preview=preview,
                    report_failure=report_failure,
                    force_display_commit=force_display_commit,
                )
            else:
                self._publish()
            return
        if immediate or self._requires_immediate_apply(snapshot, decision):
            self._timer.stop()
            self._pending_decision = None
            self._pending_snapshot = None
            self._pending_report_failure = False
            self._apply(
                snapshot,
                decision,
                preview=preview,
                report_failure=report_failure,
                force_display_commit=force_display_commit,
            )
            return

        if decision == self._pending_decision:
            self._pending_snapshot = snapshot
            self._publish()
            return

        self._pending_snapshot = snapshot
        self._pending_decision = decision
        self._pending_report_failure = report_failure
        current_reasons = self._suppression_reasons(self._applied_decision)
        next_reasons = self._suppression_reasons(decision)
        entering = bool(next_reasons) and current_reasons.issubset(next_reasons)
        self._timer.start(self.ENTER_DELAY_MS if entering else self.EXIT_DELAY_MS)
        self._publish()

    def _apply_pending(self) -> None:
        if self._pending_decision is None or self._pending_snapshot is None:
            return
        decision = self._pending_decision
        snapshot = self._pending_snapshot
        report_failure = self._pending_report_failure
        self._pending_decision = None
        self._pending_snapshot = None
        self._pending_report_failure = False
        self._apply(snapshot, decision, report_failure=report_failure)

    def _apply(
        self,
        snapshot: ContextSnapshot,
        decision: SuppressionDecision,
        *,
        preview=None,
        report_failure: bool = False,
        force_display_commit: bool = False,
    ) -> None:
        self._snapshot = snapshot
        reconcile = getattr(self._effects, "reconcile", None)
        result = None
        if callable(reconcile):
            result = reconcile(
                self._effects.intent_from_settings(
                    desired=self._desired_override,
                    global_pause=self._global_pause_override,
                    suppression=decision,
                    preview=preview,
                ),
                display_revision=self._display_revision,
                display_purpose=self._display_purpose,
                force_display_commit=force_display_commit,
            )
            self._last_result = result
            succeeded = bool(getattr(result, "succeeded", True))
        else:
            self._effects.apply(decision)
            succeeded = bool(
                getattr(self._effects, "last_apply_succeeded", True)
            )
        if result is not None:
            self.reconcile_completed.emit(result)
        if succeeded:
            self._applied_decision = decision
        elif report_failure:
            failures = getattr(self._last_result, "failures", ())
            detail = "; ".join(
                f"{failure.feature}: {failure.message}"
                for failure in failures
            ) or "unknown context effect failure"
            log.error("Context effect application failed: %s", detail)
            self.operation_failed.emit(
                "context_effect",
                "情境切换效果未能应用，请重试。",
            )
        self._publish()

    def _publish(self) -> None:
        context = self.context_state
        signature = (
            context.session,
            context.foreground_app_id,
            context.fullscreen,
            context.notification_mode,
            self._idle_bucket(context.idle_seconds),
            context.recent_app_id,
            self._effects.state,
        )
        if signature == self._last_published_signature:
            return
        self._last_published_signature = signature
        self.runtime_changed.emit(context, self._effects.state)

    def _app_rules(self) -> tuple[AppRule, ...]:
        result = []
        for rule in self._settings.app_rules:
            try:
                result.append(
                    AppRule(
                        app_id=rule["app_id"] if isinstance(rule, dict) else rule.app_id,
                        breaks=rule["breaks"] if isinstance(rule, dict) else rule.breaks,
                        focus=rule["focus"] if isinstance(rule, dict) else rule.focus,
                        filter=rule["filter"] if isinstance(rule, dict) else rule.filter,
                        dimmer=rule["dimmer"] if isinstance(rule, dict) else rule.dimmer,
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        return tuple(result)

    def _on_availability(self, available: bool, reason: str) -> None:
        if available:
            self._availability_error_reported = False
            return
        if not self._availability_error_reported:
            self._availability_error_reported = True
            self.operation_failed.emit(
                "context_unavailable",
                "情境检测不可用，已解除非安全自动暂停",
            )

    def _to_context_state(self, snapshot: ContextSnapshot) -> ContextState:
        return ContextState(
            session=snapshot.session,
            foreground_app_id=snapshot.foreground_app_id,
            fullscreen=snapshot.fullscreen,
            notification_mode=snapshot.notification_mode,
            idle_seconds=snapshot.idle_seconds,
            captured_at=snapshot.captured_at,
            recent_app_id=self._recent_app_id,
        )

    @staticmethod
    def _context_key(snapshot: ContextSnapshot) -> tuple[object, ...]:
        return (
            snapshot.session,
            snapshot.foreground_app_id,
            snapshot.fullscreen,
            snapshot.notification_mode,
            snapshot.idle_seconds >= AutoPausePolicy.IDLE_PAUSE_SECONDS,
            snapshot.idle_seconds >= AutoPausePolicy.NATURAL_REST_SECONDS,
        )

    @staticmethod
    def _idle_bucket(seconds: int) -> int:
        if seconds >= AutoPausePolicy.NATURAL_REST_SECONDS:
            return 2
        if seconds >= AutoPausePolicy.IDLE_PAUSE_SECONDS:
            return 1
        return 0

    @staticmethod
    def _suppression_reasons(decision: SuppressionDecision) -> set[str]:
        return {
            reason
            for feature in (
                decision.filter,
                decision.dimmer,
                decision.breaks,
                decision.focus,
            )
            for reason in feature.suppressed_by
        }

    @classmethod
    def _requires_immediate_apply(
        cls,
        snapshot: ContextSnapshot,
        decision: SuppressionDecision,
    ) -> bool:
        if snapshot.notification_mode == "unavailable":
            return True
        reasons = cls._suppression_reasons(decision)
        return bool(
            {
                "session_locked",
                "system_suspended",
                "presentation",
                "d3d_fullscreen",
            }.intersection(reasons)
        )
