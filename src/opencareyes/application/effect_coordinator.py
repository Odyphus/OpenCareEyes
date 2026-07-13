"""Reconcile every effect-bearing service from one immutable intent."""

from __future__ import annotations

import logging
import time
from PySide6.QtCore import QObject, Signal

from opencareyes.domain.context import FeatureSuppression, SuppressionDecision
from opencareyes.domain.runtime import (
    DesiredEffectState,
    DisplayPreview,
    ReconcileFailure,
    ReconcileResult,
    RuntimeIntent,
)
from opencareyes.state import EffectivePolicyState, FeatureRuntimeState

log = logging.getLogger(__name__)

_RESUME_TEXT = {
    "leave_fullscreen_context": "退出全屏后 2 秒恢复",
    "leave_application": "离开该应用后 2 秒恢复",
    "user_returns": "返回电脑后恢复",
    "unlock_session": "解锁后恢复",
    "resume_system": "系统唤醒后恢复",
    "all_suppressions_clear": "所有免打扰原因结束后恢复",
    "disable_hdr": "关闭 HDR 后重新检测",
}

_FEATURE_TEXT = {
    "filter": "色温效果",
    "dimmer": "屏幕调暗",
    "breaks": "休息提醒",
    "focus": "专注模式",
}


class _TransitionError(RuntimeError):
    def __init__(self, feature: str, message: str):
        super().__init__(message)
        self.feature = feature


class EffectCoordinator(QObject):
    """The only enable/disable writer for display, break and focus effects."""

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
        self._auto_paused_breaks = False
        self._natural_rest_pending = False
        self._intent = self.intent_from_settings()
        self._last_apply_succeeded = True
        self._state = self._build_state(self._intent)
        self._last_result = ReconcileResult(policy=self._state)

    @property
    def state(self) -> EffectivePolicyState:
        return self._state

    @property
    def current_intent(self) -> RuntimeIntent:
        return self._intent

    @property
    def last_result(self) -> ReconcileResult:
        return self._last_result

    @property
    def last_apply_succeeded(self) -> bool:
        """Compatibility flag used by the v0.3 context coordinator."""

        return self._last_apply_succeeded

    def intent_from_settings(
        self,
        *,
        desired: DesiredEffectState | None = None,
        suppression: SuppressionDecision | None = None,
        global_pause: bool | None = None,
        preview: DisplayPreview | None = None,
        schedule: object | None = None,
    ) -> RuntimeIntent:
        """Capture current preferences without mutating a service."""

        return RuntimeIntent(
            desired=(
                desired
                if desired is not None
                else DesiredEffectState(
                    filter=bool(getattr(self._settings, "filter_enabled", False)),
                    dimmer=bool(getattr(self._settings, "dimmer_enabled", False)),
                    breaks=bool(getattr(self._settings, "break_enabled", False)),
                    focus=bool(getattr(self._settings, "focus_enabled", False)),
                    color_temperature=int(
                        getattr(self._settings, "color_temperature", 6500)
                    ),
                    dim_level=int(getattr(self._settings, "dim_level", 0)),
                    focus_dim_level=int(
                        getattr(self._settings, "focus_dim_level", 150)
                    ),
                )
            ),
            schedule=schedule,
            suppression=(
                suppression
                if suppression is not None
                else getattr(self, "_intent", RuntimeIntent()).suppression
            ),
            global_pause=(
                self._is_globally_paused()
                if global_pause is None
                else bool(global_pause)
            ),
            preview=preview,
        )

    def reconcile(
        self,
        intent: RuntimeIntent,
        *,
        display_revision: int = 0,
        display_purpose: str = "system",
        force_display_commit: bool = False,
    ) -> ReconcileResult:
        """Apply one complete intent, compensating every partial transition."""

        if not isinstance(intent, RuntimeIntent):
            raise TypeError("intent must be a RuntimeIntent")
        before = self._capture_before_state()
        previous_intent = self._intent
        pending_requests: list[object] = []
        try:
            request = self._reconcile_filter(
                intent,
                previous_intent,
                display_revision=display_revision,
                display_purpose=display_purpose,
                force_display_commit=force_display_commit,
            )
            if request is not None:
                pending_requests.append(request)
            self._reconcile_dimmer(intent, previous_intent)
            self._reconcile_focus(intent, previous_intent)
            self._reconcile_breaks(intent)
        except _TransitionError as exc:
            self._last_apply_succeeded = False
            self._intent = previous_intent
            feature_text = _FEATURE_TEXT.get(exc.feature, "运行时效果")
            message = f"{feature_text}未能应用，请重试。"
            failure = ReconcileFailure(exc.feature, str(exc))
            log.error("Effect reconciliation failed [%s]: %s", exc.feature, exc)
            self.operation_failed.emit("context_effect", message)
            rollback_succeeded = self._restore_before_state(before)
            policy = self._publish_state()
            self._last_result = ReconcileResult(
                policy=policy,
                failures=(failure,),
                rollback_succeeded=rollback_succeeded,
                pending_requests=tuple(pending_requests),
            )
            return self._last_result
        except Exception as exc:  # defensive service boundary
            self._last_apply_succeeded = False
            self._intent = previous_intent
            message = "运行时效果未能应用，请重试。"
            log.exception("Unexpected effect reconciliation failure")
            self.operation_failed.emit("context_effect", message)
            rollback_succeeded = self._restore_before_state(before)
            policy = self._publish_state()
            self._last_result = ReconcileResult(
                policy=policy,
                failures=(ReconcileFailure("runtime", str(exc)),),
                rollback_succeeded=rollback_succeeded,
                pending_requests=tuple(pending_requests),
            )
            return self._last_result

        self._intent = intent
        self._last_apply_succeeded = True
        policy = self._publish_state()
        self._last_result = ReconcileResult(
            policy=policy,
            pending_requests=tuple(pending_requests),
        )
        return self._last_result

    def apply(self, decision: SuppressionDecision) -> EffectivePolicyState:
        """Compatibility wrapper for v0.3 callers."""

        return self.reconcile(
            self.intent_from_settings(suppression=decision)
        ).policy

    def refresh(self) -> EffectivePolicyState:
        """Re-project actual service state without writing an effect."""

        return self._publish_state()

    def _reconcile_filter(
        self,
        intent: RuntimeIntent,
        previous: RuntimeIntent,
        *,
        display_revision: int,
        display_purpose: str,
        force_display_commit: bool,
    ) -> object | None:
        suppression = intent.suppression.filter.suppressed
        hdr_active = bool(getattr(self._blue_filter, "hdr_active", False))
        target = (
            intent.desired.filter
            and not intent.global_pause
            and not suppression
            and not hdr_active
        )
        temperature = self._temperature(intent)
        previous_temperature = self._temperature(previous)
        service = self._blue_filter
        request_enable = getattr(service, "request_enable", None)
        request_temperature = getattr(service, "request_temperature", None)
        preview_temperature = getattr(service, "preview_temperature", None)

        def enable():
            if callable(request_enable):
                return request_enable(
                    temperature,
                    revision=display_revision,
                    purpose=display_purpose,
                )
            return service.enable(temperature)

        def update_temperature():
            if intent.preview is not None and callable(preview_temperature):
                return preview_temperature(
                    temperature,
                    revision=display_revision,
                )
            if callable(request_temperature):
                return request_temperature(
                    temperature,
                    revision=display_revision,
                    purpose=display_purpose,
                )
            return service.set_temperature(temperature)

        commit_after_preview = (
            intent.preview is None
            and previous.preview is not None
            and previous.preview.color_temperature is not None
        )
        return self._apply_toggle(
            "filter",
            service,
            target,
            enable,
            parameter_changed=(
                temperature != previous_temperature
                or commit_after_preview
                or force_display_commit
            ),
            update_parameter=update_temperature,
            revision=display_revision,
            purpose=display_purpose,
            force_barrier=force_display_commit,
        )

    def _reconcile_dimmer(
        self,
        intent: RuntimeIntent,
        previous: RuntimeIntent,
    ) -> None:
        target = (
            intent.desired.dimmer
            and not intent.global_pause
            and not intent.suppression.dimmer.suppressed
        )
        level = self._dim_level(intent)
        previous_level = self._dim_level(previous)
        self._apply_toggle(
            "dimmer",
            self._dimmer,
            target,
            lambda: self._dimmer.enable(level),
            parameter_changed=level != previous_level,
            update_parameter=lambda: self._dimmer.set_brightness(level),
        )

    def _reconcile_focus(
        self,
        intent: RuntimeIntent,
        previous: RuntimeIntent,
    ) -> None:
        target = (
            intent.desired.focus
            and not intent.global_pause
            and not intent.suppression.focus.suppressed
        )
        level_changed = (
            intent.desired.focus_dim_level != previous.desired.focus_dim_level
        )
        self._apply_toggle(
            "focus",
            self._focus_mode,
            target,
            self._focus_mode.enable if self._focus_mode is not None else None,
            parameter_changed=level_changed,
            update_parameter=(
                lambda: self._focus_mode.set_dim_level(
                    intent.desired.focus_dim_level
                )
                if self._focus_mode is not None
                else None
            ),
        )

    def _reconcile_breaks(self, intent: RuntimeIntent) -> None:
        reminder = self._break_reminder
        desired = intent.desired.breaks
        suppressed = intent.suppression.breaks.suppressed
        if intent.suppression.natural_rest:
            self._natural_rest_pending = True

        if reminder is None:
            if desired and not intent.global_pause and not suppressed:
                raise _TransitionError("breaks", "休息提醒服务不可用")
            return

        try:
            if not desired:
                if bool(getattr(reminder, "enabled", False)) or bool(
                    getattr(reminder, "suspended", False)
                ):
                    reminder.stop()
                self._auto_paused_breaks = False
                self._natural_rest_pending = False
                return

            if intent.global_pause or suppressed:
                if not bool(getattr(reminder, "suspended", False)):
                    suspend = getattr(reminder, "suspend", None)
                    if callable(suspend):
                        if bool(getattr(reminder, "enabled", False)):
                            suspend()
                    elif bool(getattr(reminder, "enabled", False)) and not bool(
                        getattr(reminder, "paused", False)
                    ):
                        reminder.pause()
                self._auto_paused_breaks = bool(
                    getattr(reminder, "suspended", False)
                    or getattr(reminder, "paused", False)
                )
                return

            if self._natural_rest_pending:
                complete = getattr(reminder, "complete_natural_rest", None)
                if callable(complete):
                    complete()
                else:
                    reminder.start()
                if bool(getattr(reminder, "suspended", False)):
                    reminder.resume_from_suspend()
                elif not bool(getattr(reminder, "enabled", False)):
                    reminder.start()
                self._natural_rest_pending = False
                self._auto_paused_breaks = False
            elif bool(getattr(reminder, "suspended", False)):
                reminder.resume_from_suspend()
                self._auto_paused_breaks = False
            elif not bool(getattr(reminder, "enabled", False)):
                reminder.start()
                self._auto_paused_breaks = False
            elif self._auto_paused_breaks and bool(
                getattr(reminder, "paused", False)
            ):
                reminder.resume()
                self._auto_paused_breaks = False
        except Exception as exc:
            raise _TransitionError("breaks", str(exc)) from exc

        if not bool(getattr(reminder, "enabled", False)):
            raise _TransitionError("breaks", "服务未进入启用状态")

    @staticmethod
    def _apply_toggle(
        feature: str,
        service,
        target: bool,
        enable,
        *,
        parameter_changed: bool = False,
        update_parameter=None,
        revision: int = 0,
        purpose: str = "system",
        force_barrier: bool = False,
    ) -> object | None:
        if service is None:
            if target:
                raise _TransitionError(feature, "所需服务不可用")
            return None
        actual = bool(getattr(service, "enabled", False))
        pending = bool(getattr(service, "pending", False))
        pending_target = getattr(service, "pending_target", None)
        operation_result = None
        try:
            if target and force_barrier:
                if not actual:
                    if enable is None:
                        raise RuntimeError("服务无法启用")
                    result = enable()
                elif update_parameter is not None:
                    result = update_parameter()
                else:
                    result = True
                if result is False:
                    raise RuntimeError("原生操作被拒绝")
                operation_result = result
            elif target and (not actual or pending_target is False):
                if pending_target is True and not actual:
                    if parameter_changed and update_parameter is not None:
                        result = update_parameter()
                        if result is False:
                            raise RuntimeError("参数应用失败")
                        operation_result = result
                    return EffectCoordinator._request_token(operation_result)
                if enable is None:
                    raise RuntimeError("服务无法启用")
                result = enable()
                if result is False:
                    raise RuntimeError("原生操作被拒绝")
                operation_result = result
            elif target and parameter_changed and update_parameter is not None:
                result = update_parameter()
                if result is False:
                    raise RuntimeError("参数应用失败")
                operation_result = result
            elif not target and force_barrier:
                request_disable = getattr(service, "request_disable", None)
                if callable(request_disable):
                    result = request_disable(
                        revision=revision,
                        purpose=purpose,
                    )
                elif actual or pending_target is True:
                    result = service.disable()
                else:
                    result = True
                if result is False:
                    raise RuntimeError("原生操作被拒绝")
                operation_result = result
            elif not target and (actual or pending_target is True):
                if pending_target is False and actual:
                    return None
                request_disable = getattr(service, "request_disable", None)
                result = (
                    request_disable(revision=revision, purpose=purpose)
                    if callable(request_disable)
                    else service.disable()
                )
                if result is False:
                    raise RuntimeError("原生操作被拒绝")
                operation_result = result
        except _TransitionError:
            raise
        except Exception as exc:
            raise _TransitionError(feature, str(exc)) from exc

        if bool(getattr(service, "pending", pending)):
            return EffectCoordinator._request_token(operation_result)
        if bool(getattr(service, "enabled", False)) != bool(target):
            raise _TransitionError(feature, "服务未进入请求的状态")
        return None

    @staticmethod
    def _request_token(result) -> object | None:
        if result is None or isinstance(result, bool):
            return None
        return result

    def _capture_before_state(self) -> dict[str, object]:
        reminder = self._break_reminder
        return {
            "filter": self._service_target(self._blue_filter),
            "filter_level": (
                self._temperature(self._intent)
                if bool(getattr(self._blue_filter, "pending", False))
                else self._service_value(
                    self._blue_filter,
                    ("current_temperature", "level"),
                    self._temperature(self._intent),
                )
            ),
            "dimmer": bool(getattr(self._dimmer, "enabled", False)),
            "dimmer_level": self._service_value(
                self._dimmer,
                ("dim_level", "level"),
                self._dim_level(self._intent),
            ),
            "focus": bool(getattr(self._focus_mode, "enabled", False)),
            "focus_level": self._service_value(
                self._focus_mode,
                ("dim_level", "level"),
                self._intent.desired.focus_dim_level,
            ),
            "break_enabled": bool(getattr(reminder, "enabled", False)),
            "break_paused": bool(getattr(reminder, "paused", False)),
            "break_suspended": bool(getattr(reminder, "suspended", False)),
            "auto_paused": self._auto_paused_breaks,
            "natural_rest": self._natural_rest_pending,
        }

    def _restore_before_state(self, before: dict[str, object]) -> bool:
        failures: list[str] = []
        for name, service, enabled, level, enable, update in (
            (
                "filter",
                self._blue_filter,
                before["filter"],
                before["filter_level"],
                lambda value: self._blue_filter.enable(value),
                lambda value: self._blue_filter.set_temperature(value),
            ),
            (
                "dimmer",
                self._dimmer,
                before["dimmer"],
                before["dimmer_level"],
                lambda value: self._dimmer.enable(value),
                lambda value: self._dimmer.set_brightness(value),
            ),
            (
                "focus",
                self._focus_mode,
                before["focus"],
                before["focus_level"],
                lambda _value: self._focus_mode.enable(),
                lambda value: self._focus_mode.set_dim_level(value),
            ),
        ):
            if service is None:
                continue
            try:
                actual = bool(getattr(service, "enabled", False))
                pending_target = getattr(service, "pending_target", None)
                if enabled:
                    result = (
                        enable(level)
                        if not actual or pending_target is False
                        else update(level)
                    )
                    if result is False:
                        raise RuntimeError("原生回滚操作被拒绝")
                elif actual or pending_target is True:
                    result = service.disable()
                    if result is False:
                        raise RuntimeError("原生回滚操作被拒绝")
                if not bool(getattr(service, "pending", False)) and (
                    bool(getattr(service, "enabled", False)) != bool(enabled)
                ):
                    raise RuntimeError("回滚状态验证失败")
            except Exception as exc:  # fault-injection boundary
                failures.append(f"{name}: {exc}")

        reminder = self._break_reminder
        if reminder is not None:
            try:
                if before["break_suspended"]:
                    if not bool(getattr(reminder, "suspended", False)):
                        if not bool(getattr(reminder, "enabled", False)):
                            reminder.start()
                        suspend = getattr(reminder, "suspend", None)
                        if callable(suspend):
                            suspend()
                        else:
                            reminder.pause()
                elif not before["break_enabled"]:
                    reminder.stop()
                else:
                    if bool(getattr(reminder, "suspended", False)):
                        reminder.resume_from_suspend()
                    if not bool(getattr(reminder, "enabled", False)):
                        reminder.start()
                    if before["break_paused"] and not bool(
                        getattr(reminder, "paused", False)
                    ):
                        reminder.pause()
                    elif not before["break_paused"] and bool(
                        getattr(reminder, "paused", False)
                    ):
                        reminder.resume()
                    if not before["break_suspended"] and (
                        bool(getattr(reminder, "enabled", False))
                        != bool(before["break_enabled"])
                        or bool(getattr(reminder, "paused", False))
                        != bool(before["break_paused"])
                    ):
                        raise RuntimeError("回滚状态验证失败")
            except Exception as exc:
                failures.append(f"breaks: {exc}")
        self._auto_paused_breaks = bool(before["auto_paused"])
        self._natural_rest_pending = bool(before["natural_rest"])
        if failures:
            log.error("Effect compensation incomplete: %s", "; ".join(failures))
            self.operation_failed.emit(
                "context_compensation",
                "效果回滚不完整，请重启 OpenCareEyes 后检查设置。",
            )
        return not failures

    def _publish_state(self) -> EffectivePolicyState:
        state = self._build_state(self._intent)
        if state != self._state:
            self._state = state
            self.state_changed.emit(state)
        return self._state

    def _build_state(self, intent: RuntimeIntent) -> EffectivePolicyState:
        decision = intent.suppression
        global_reason = ("global_pause",) if intent.global_pause else ()

        def feature(
            name: str,
            desired: bool,
            service,
            suppression: FeatureSuppression,
        ) -> FeatureRuntimeState:
            extra = ()
            resume_condition = suppression.resume_condition
            if name == "filter" and bool(
                getattr(self._blue_filter, "hdr_active", False)
            ):
                extra = ("hdr_active",)
                resume_condition = "disable_hdr"
            reasons = global_reason + self._normalise_reasons(
                suppression.suppressed_by
            ) + extra
            actual = bool(getattr(service, "enabled", False))
            if name == "breaks":
                actual = actual and not bool(getattr(service, "paused", False))
            return FeatureRuntimeState(
                desired_enabled=desired,
                effective_enabled=actual and not bool(reasons),
                suppressed_by=tuple(dict.fromkeys(reasons)),
                resume_condition=(
                    "等待手动恢复"
                    if global_reason
                    else _RESUME_TEXT.get(resume_condition, "情境结束后恢复")
                ),
            )

        return EffectivePolicyState(
            filter=feature(
                "filter", intent.desired.filter, self._blue_filter, decision.filter
            ),
            dimmer=feature(
                "dimmer", intent.desired.dimmer, self._dimmer, decision.dimmer
            ),
            breaks=feature(
                "breaks", intent.desired.breaks, self._break_reminder, decision.breaks
            ),
            focus=feature(
                "focus", intent.desired.focus, self._focus_mode, decision.focus
            ),
        )

    @staticmethod
    def _normalise_reasons(reasons: tuple[str, ...]) -> tuple[str, ...]:
        result: list[str] = []
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

    @staticmethod
    def _temperature(intent: RuntimeIntent) -> int:
        if intent.preview is not None and intent.preview.color_temperature is not None:
            return int(intent.preview.color_temperature)
        return int(intent.desired.color_temperature)

    @staticmethod
    def _dim_level(intent: RuntimeIntent) -> int:
        if intent.preview is not None and intent.preview.dim_level is not None:
            return int(intent.preview.dim_level)
        return int(intent.desired.dim_level)

    @staticmethod
    def _service_value(service, names: tuple[str, ...], default: int) -> int:
        if service is not None:
            for name in names:
                value = getattr(service, name, None)
                if isinstance(value, (int, float)):
                    return int(value)
        return int(default)

    @staticmethod
    def _service_target(service) -> bool:
        pending_target = getattr(service, "pending_target", None)
        if pending_target is not None:
            return bool(pending_target)
        return bool(getattr(service, "enabled", False))

    def _is_globally_paused(self) -> bool:
        mode = getattr(self._settings, "global_pause_mode", "none")
        if mode != "timed":
            return mode in {"manual", "next_schedule"}
        until = getattr(self._settings, "global_pause_until", None)
        return until is not None and until > time.time()
