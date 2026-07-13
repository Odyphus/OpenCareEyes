"""Single write entry point for OpenCareEyes application state."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from PySide6.QtCore import (
    QObject,
    QRunnable,
    QThreadPool,
    QTimer,
    Qt,
    Signal,
    Slot,
)

from opencareyes.application.effect_coordinator import EffectCoordinator
from opencareyes.application.state_projector import StateProjector
from opencareyes.constants import (
    DIM_MAX,
    DIM_MIN,
    APP_VERSION,
    HOTKEY_TOGGLE_BREAK,
    HOTKEY_TOGGLE_DIMMER,
    HOTKEY_TOGGLE_FILTER,
    HOTKEY_TOGGLE_FOCUS,
    TEMP_MAX,
    TEMP_MIN,
)
from opencareyes.diagnostics import export_diagnostics as write_diagnostics
from opencareyes.domain.runtime import (
    DesiredEffectState,
    DisplayPreview,
    ReconcileResult,
)
from opencareyes.state import (
    AppState,
    ContextState,
    DisplayState,
    EffectivePolicyState,
    GlobalPauseState,
    UpdateState,
)

if TYPE_CHECKING:
    from opencareyes.config.settings import Settings
    from opencareyes.core.break_reminder import BreakReminder
    from opencareyes.core.scheduler import Scheduler
    from opencareyes.platform.hotkeys import HotkeyManager

log = logging.getLogger(__name__)

_SCHEDULE_SETTING_KEYS = (
    "filter/schedule_enabled",
    "automation/mode",
    "automation/on_time",
    "automation/off_time",
    "automation/days",
    "automation/day_profile",
    "automation/night_profile",
    "automation/sunrise_offset",
    "automation/sunset_offset",
    "location/latitude",
    "location/longitude",
    "location/configured",
    "location/city",
)


def _user_failure_message(code: str) -> str:
    """Return a fixed Chinese message without exposing backend details."""

    normalized = str(code).strip().casefold()
    if normalized.endswith("_rollback"):
        return "操作回滚不完整，请重启 OpenCareEyes 后检查设置。"
    message_groups = (
        (
            ("diagnostics",),
            "诊断信息未能导出，请检查目标文件夹权限后重试。",
        ),
        (
            (
                "filter",
                "dimmer",
                "display",
                "unknown_display",
                "restore_filter",
                "restore_dimmer",
            ),
            "显示效果未能应用，请重试。",
        ),
        (
            ("break", "force_break", "restore_break"),
            "休息提醒操作未能完成，请重试。",
        ),
        (
            ("focus", "restore_focus"),
            "专注模式操作未能完成，请重试。",
        ),
        (
            ("schedule", "location", "restore_schedule"),
            "自动化设置未能保存，请检查设置后重试。",
        ),
        (("global",), "全部效果暂停操作未能完成，请重试。"),
        (
            ("hotkey",),
            "快捷键设置未能保存，请检查组合键是否被占用。",
        ),
        (
            (
                "app_rule",
                "context",
                "smart_pause",
                "fullscreen_pause",
                "natural_rest",
            ),
            "智能免打扰设置未能保存，请重试。",
        ),
        (
            (
                "theme",
                "motion",
                "autostart",
                "pet",
                "onboarding",
                "settings",
            ),
            "本地设置未能保存，请重试。",
        ),
        (("restore",), "启动恢复未能完成，请在主界面检查各项效果。"),
    )
    for prefixes, message in message_groups:
        if normalized.startswith(prefixes):
            return message
    return "当前操作未能完成，请重试。"


@dataclass(frozen=True, slots=True)
class _OwnedSettingsSnapshot:
    keys: tuple[str, ...]
    values: dict[str, object]


@dataclass(slots=True)
class _RuntimeTransaction:
    """Staged display/pause intent gated by verified native results."""

    revision: int
    code: str
    baseline: DisplayState
    proposal: DisplayState
    desired: DesiredEffectState
    baseline_pause_mode: str = "none"
    baseline_pause_until: float | None = None
    proposal_pause_mode: str = "none"
    proposal_pause_until: float | None = None
    owns_display: bool = True
    owns_pause: bool = False
    request_ids: set[int] = field(default_factory=set)
    latest_request_ids: dict[tuple[str, str], int] = field(
        default_factory=dict
    )
    disable_focus: bool = False
    manual_override_claimed: bool = False
    manual_override_baseline: bool = False
    settings_snapshot: object | None = None
    scheduler_snapshot: object | None = None
    settings_proposal: object | None = None
    scheduler_proposal: object | None = None
    owned_configuration_restored: bool = False


class _UpdateWorkerSignals(QObject):
    finished = Signal(object)


class _UpdateWorker(QRunnable):
    def __init__(self, service):
        super().__init__()
        self._service = service
        self.signals = _UpdateWorkerSignals()

    @Slot()
    def run(self) -> None:
        try:
            state = self._service.check_for_updates()
        except Exception:
            current = str(getattr(self._service.state, "current_version", ""))
            state = UpdateState("failed", current)
        self.signals.finished.emit(state)


class AppController(QObject):
    """Own all feature mutations and publish immutable snapshots."""

    state_changed = Signal(object)
    break_tick = Signal(int, int)
    operation_failed = Signal(str, str)
    notification_requested = Signal(str, str)

    def __init__(
        self,
        settings: Settings,
        blue_filter=None,
        dimmer=None,
        break_reminder: BreakReminder | None = None,
        focus_mode=None,
        scheduler: Scheduler | None = None,
        hotkeys: HotkeyManager | None = None,
        effect_coordinator: EffectCoordinator | None = None,
        update_service=None,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self._settings = settings
        self._blue_filter = blue_filter
        self._dimmer = dimmer
        self._break_reminder = break_reminder
        self._focus_mode = focus_mode
        self._scheduler = scheduler
        self._hotkeys = hotkeys
        self._effects = effect_coordinator or EffectCoordinator(
            settings,
            blue_filter=blue_filter,
            dimmer=dimmer,
            break_reminder=break_reminder,
            focus_mode=focus_mode,
        )
        self._update_service = update_service
        self._update_state = (
            update_service.state
            if update_service is not None
            else UpdateState("idle", APP_VERSION)
        )
        self._update_workers: dict[QObject, QRunnable] = {}
        self._context_runtime = None
        self._restored = False
        self._in_transaction = False
        self._runtime_revision = 0
        self._runtime_transaction: _RuntimeTransaction | None = None
        self._runtime_compensation_ids: dict[int, str] = {}
        self._last_display_hdr_active = bool(
            getattr(blue_filter, "hdr_active", False)
        )
        self._context_state = ContextState()
        self._effective_policy: EffectivePolicyState | None = self._effects.state
        self._state_projector = StateProjector(
            settings,
            blue_filter=blue_filter,
            dimmer=dimmer,
            break_reminder=break_reminder,
            focus_mode=focus_mode,
            scheduler=scheduler,
            hotkeys=hotkeys,
        )

        self._pause_timer = QTimer(self)
        self._pause_timer.setSingleShot(True)
        self._pause_timer.timeout.connect(self.resume_all)
        self._focus_timer = QTimer(self)
        self._focus_timer.setSingleShot(True)
        self._focus_timer.timeout.connect(self._on_focus_session_timeout)
        self._focus_session_ends_at: datetime | None = None
        self._break_semantic_snapshot = self._break_semantic_key()

        if self._break_reminder is not None:
            if hasattr(self._break_reminder, "tick"):
                self._break_reminder.tick.connect(self._on_break_tick)
            if hasattr(self._break_reminder, "state_changed"):
                self._break_reminder.state_changed.connect(
                    self._on_break_service_state_changed
                )
            self._break_reminder.break_started.connect(
                lambda: self.notification_requested.emit(
                    "休息时间", "看看远处，让眼睛放松一下。"
                )
            )

        if self._scheduler is not None:
            set_profile_callback = getattr(
                self._scheduler, "set_profile_callback", None
            )
            if callable(set_profile_callback):
                set_profile_callback(self._on_scheduled_profile_requested)
            else:
                self._scheduler.set_state_callback(
                    self._on_scheduled_filter_state_requested
                )
            self._scheduler.next_event_changed.connect(self.refresh_state)
            self._scheduler.running_changed.connect(self.refresh_state)
            self._scheduler.manual_override_changed.connect(self.refresh_state)
            self._scheduler.error.connect(self.operation_failed)

        if self._hotkeys is not None:
            self._hotkeys.registration_failed.connect(self.operation_failed)
            self._hotkeys.callback_failed.connect(self.operation_failed)

        self._effects.state_changed.connect(self._on_effective_policy_changed)
        if self._blue_filter is not None:
            request_finished = getattr(
                self._blue_filter, "request_finished", None
            )
            if request_finished is not None:
                request_finished.connect(
                    self._on_display_request_finished,
                    Qt.QueuedConnection,
                )
            display_state_changed = getattr(
                self._blue_filter, "state_changed", None
            )
            if display_state_changed is not None:
                display_state_changed.connect(
                    self._on_display_service_state_changed,
                    Qt.QueuedConnection,
                )
            display_failure = getattr(
                self._blue_filter, "operation_failed", None
            )
            if request_finished is None and display_failure is not None:
                display_failure.connect(
                    self.operation_failed,
                    Qt.QueuedConnection,
                )

        self._state = self._build_state()

    @property
    def state(self) -> AppState:
        return self._state

    @property
    def settings(self) -> Settings:
        return self._settings

    @property
    def effect_coordinator(self) -> EffectCoordinator:
        """The process-wide effect boundary used by every command source."""

        return self._effects

    def restore(self) -> bool:
        """Apply persisted configuration to services once at startup."""
        success = True
        try:
            self._apply_break_configuration_from_settings()
            if self._focus_mode is not None:
                self._focus_mode.set_dim_level(self._settings.focus_dim_level)
        except Exception as exc:
            success = False
            self._fail("restore_configuration", exc)

        pause_active = self._restore_pause_deadline()
        if not pause_active:
            success = self._restore_configured_services() and success
        else:
            success = self._disable_effects_for_pause() and success

        if self._scheduler is not None:
            try:
                if self._settings.filter_schedule_enabled:
                    self._scheduler.start()
                else:
                    self._scheduler.stop()
            except Exception as exc:
                success = False
                self._fail("restore_schedule", exc)

        if self._hotkeys is not None:
            success = self._register_hotkeys() and success

        self._restored = True
        self.refresh_state()
        return success

    def refresh_state(self, *_args, force: bool = False) -> AppState:
        if self._in_transaction and not force:
            return self._state
        new_state = self._build_state()
        if force or new_state != self._state:
            self._state = new_state
            self.state_changed.emit(new_state)
        return self._state

    def update_runtime_state(
        self,
        context: ContextState,
        effective_policy: EffectivePolicyState,
    ) -> AppState:
        """Receive the context layer's read-only runtime projection."""

        self._context_state = context
        self._effective_policy = effective_policy
        if self._in_transaction:
            return self._state
        return self.refresh_state()

    def attach_context_runtime(self, runtime) -> None:
        """Attach the context application layer after all services exist."""

        self._context_runtime = runtime
        runtime_effects = getattr(runtime, "effects", None)
        if runtime_effects is not None and runtime_effects is not self._effects:
            try:
                self._effects.state_changed.disconnect(
                    self._on_effective_policy_changed
                )
            except (RuntimeError, TypeError):
                pass
            self._effects = runtime_effects
            self._effects.state_changed.connect(
                self._on_effective_policy_changed
            )
            self._effective_policy = self._effects.state
        runtime.runtime_changed.connect(self.update_runtime_state)
        failure = getattr(runtime, "operation_failed", None)
        if failure is not None:
            failure.connect(self.operation_failed)
        reconcile_completed = getattr(
            runtime,
            "reconcile_completed",
            None,
        )
        if reconcile_completed is not None:
            reconcile_completed.connect(
                self._on_context_reconcile_completed
            )
        runtime.recompute()

    # ---- Feature switches ----

    def set_feature_enabled(self, feature: str, enabled: bool) -> bool:
        handlers = {
            "filter": self.set_filter_enabled,
            "dimmer": self.set_dimmer_enabled,
            "break": self.set_break_enabled,
            "breaks": self.set_break_enabled,
            "focus": self.set_focus_enabled,
            "schedule": lambda value: self.set_schedule(value),
            "automation": lambda value: self.set_schedule(value),
        }
        handler = handlers.get(feature.strip().lower())
        if handler is None:
            self.operation_failed.emit("unknown_feature", "不支持该功能设置。")
            return False
        return handler(bool(enabled))

    def set_filter_enabled(self, enabled: bool) -> bool:
        enabled = bool(enabled)
        proposal = replace(
            self._current_display_state(),
            filter_enabled=enabled,
        )
        return self._start_display_transaction(
            "filter_toggle",
            proposal,
            mark_manual_override=True,
        )

    def set_dimmer_enabled(self, enabled: bool) -> bool:
        enabled = bool(enabled)
        proposal = replace(
            self._current_display_state(),
            dimmer_enabled=enabled,
        )
        return self._start_display_transaction("dimmer_toggle", proposal)

    def set_break_enabled(self, enabled: bool) -> bool:
        enabled = bool(enabled)

        def operation() -> None:
            self._require_service(self._break_reminder, "break reminder")
            self._settings.break_enabled = enabled

        return self._run("break_toggle", operation)

    def set_focus_enabled(self, enabled: bool) -> bool:
        enabled = bool(enabled)
        transaction = self._runtime_transaction
        previous_disable_focus = bool(
            transaction is not None and transaction.disable_focus
        )

        def operation() -> None:
            self._require_service(self._focus_mode, "focus mode")
            if self._runtime_transaction is transaction and transaction is not None:
                transaction.disable_focus = False
            self._settings.focus_enabled = enabled
            if not enabled:
                self._focus_timer.stop()
                self._focus_session_ends_at = None

        return self._run(
            "focus_toggle",
            operation,
            rollback=(
                None
                if transaction is None
                else lambda: setattr(
                    transaction,
                    "disable_focus",
                    previous_disable_focus,
                )
            ),
        )

    # ---- Display and break configuration ----

    def set_color_temperature(self, kelvin: int, persist: bool = True) -> bool:
        kelvin = max(TEMP_MIN, min(TEMP_MAX, int(kelvin)))
        try:
            self._require_service(self._blue_filter, "blue-light filter")
        except Exception as exc:
            self._fail("filter_temperature", exc)
            return False
        proposal = replace(
            self._current_display_state(),
            color_temperature=kelvin,
            preset="custom",
        )
        if not persist:
            return self._preview_display(
                "filter_temperature",
                DisplayPreview(color_temperature=kelvin),
            )
        return self._start_display_transaction(
            "filter_temperature",
            proposal,
        )

    def set_dim_level(self, level: int, persist: bool = True) -> bool:
        level = max(DIM_MIN, min(DIM_MAX, int(level)))
        try:
            self._require_service(self._dimmer, "screen dimmer")
        except Exception as exc:
            self._fail("dimmer_level", exc)
            return False
        proposal = replace(
            self._current_display_state(),
            dim_level=level,
            preset="custom",
        )
        if not persist:
            return self._preview_display(
                "dimmer_level",
                DisplayPreview(dim_level=level),
            )
        return self._start_display_transaction("dimmer_level", proposal)

    def set_focus_dim_level(self, level: int) -> bool:
        level = max(0, min(255, int(level)))

        def operation() -> None:
            self._require_service(self._focus_mode, "focus mode")
            self._settings.focus_dim_level = level

        return self._run("focus_dim_level", operation)

    def set_break_mode(self, mode: str) -> bool:
        def operation() -> None:
            self._require_service(self._break_reminder, "break reminder")
            self._break_reminder.set_mode(mode)
            self._settings.break_mode = mode
            if hasattr(self._settings, "cadence_mode"):
                self._settings.cadence_mode = mode
            self._settings.work_duration = self._break_reminder.work_duration
            self._settings.break_duration = self._break_reminder.break_duration
            self._persist_break_configuration()

        return self._run("break_mode", operation)

    def set_break_durations(self, work_seconds: int, break_seconds: int) -> bool:
        return self.set_break_cadence(
            max(1, int(work_seconds)),
            max(1, int(break_seconds)),
            bool(getattr(self._settings, "cadence_long_enabled", False)),
            int(getattr(self._settings, "cadence_long_interval", 60 * 60)),
            int(getattr(self._settings, "cadence_long_duration", 5 * 60)),
        )

    def set_break_cadence(
        self,
        short_interval: int,
        short_duration: int,
        long_enabled: bool,
        long_interval: int,
        long_duration: int,
    ) -> bool:
        values = (
            max(1, int(short_interval)),
            max(1, int(short_duration)),
            bool(long_enabled),
            max(1, int(long_interval)),
            max(1, int(long_duration)),
        )
        if values[2] and values[3] <= values[0]:
            self.operation_failed.emit(
                "break_cadence", "长休息周期必须大于短休息周期"
            )
            return False

        def operation() -> None:
            self._require_service(self._break_reminder, "break reminder")
            configure = getattr(self._break_reminder, "configure_cadence", None)
            if callable(configure):
                configure(
                    mode="custom",
                    short_interval=values[0],
                    short_duration=values[1],
                    long_enabled=values[2],
                    long_interval=values[3],
                    long_duration=values[4],
                )
            else:
                self._break_reminder.set_mode("custom")
                self._break_reminder.set_work_duration(values[0])
                self._break_reminder.set_break_duration(values[1])
            self._settings.break_mode = "custom"
            self._settings.work_duration = values[0]
            self._settings.break_duration = values[1]
            if hasattr(self._settings, "cadence_mode"):
                self._settings.cadence_mode = "custom"
                self._settings.cadence_short_interval = values[0]
                self._settings.cadence_short_duration = values[1]
                self._settings.cadence_long_enabled = values[2]
                self._settings.cadence_long_interval = values[3]
                self._settings.cadence_long_duration = values[4]

        return self._run("break_cadence", operation)

    def set_break_reminder_style(self, style: str) -> bool:
        if style not in {"progressive", "fullscreen"}:
            self.operation_failed.emit(
                "break_reminder_style", "不支持该休息提醒方式。"
            )
            return False

        def operation() -> None:
            self._require_and_call(
                self._break_reminder,
                "set_reminder_style",
                style,
            )
            self._settings.break_reminder_style = style

        return self._run("break_reminder_style", operation)

    def start_due_break(self) -> bool:
        def operation() -> None:
            self._require_service(self._break_reminder, "break reminder")
            if not self._break_reminder.start_due_break():
                raise RuntimeError("当前没有待开始的休息")

        return self._run("break_start_due", operation, reconcile=False)

    def set_force_break(self, enabled: bool) -> bool:
        def operation() -> None:
            self._require_service(self._break_reminder, "break reminder")
            self._break_reminder.force_break = bool(enabled)
            self._settings.force_break = bool(enabled)

        return self._run("force_break", operation)

    def set_break_countdown_display(self, mode: str) -> bool:
        if mode not in {"floating", "tray", "hidden"}:
            self.operation_failed.emit(
                "break_display",
                "不支持该倒计时显示方式。",
            )
            return False
        return self._run(
            "break_display",
            lambda: setattr(self._settings, "break_countdown_display", mode),
        )

    def pause_break(self) -> bool:
        return self._run(
            "break_pause",
            lambda: self._require_and_call(self._break_reminder, "pause"),
        )

    def resume_break(self) -> bool:
        return self._run(
            "break_resume",
            lambda: self._require_and_call(self._break_reminder, "resume"),
        )

    def snooze_break(self, minutes: int = 5) -> bool:
        minutes = max(1, int(minutes))

        def operation() -> None:
            self._require_service(self._break_reminder, "break reminder")
            if self._break_reminder.force_break:
                raise ValueError("严格休息模式下不能稍后提醒")
            self._break_reminder.snooze(minutes * 60)

        return self._run(
            "break_snooze",
            operation,
        )

    def skip_break(self) -> bool:
        return self._run(
            "break_skip",
            lambda: self._require_and_call(self._break_reminder, "skip_break"),
        )

    def apply_display_profile(
        self,
        name: str,
        *,
        mark_manual_override: bool = True,
    ) -> bool:
        try:
            proposal = self._display_profile_state(name)
        except (KeyError, ImportError, SyntaxError, ValueError) as exc:
            self._fail("unknown_display_profile", exc)
            return False
        try:
            self._require_service(self._blue_filter, "blue-light filter")
            if proposal.dim_level > 0:
                self._require_service(self._dimmer, "screen dimmer")
        except Exception as exc:
            self._fail("display_profile", exc)
            return False
        return self._start_display_transaction(
            "display_profile",
            proposal,
            mark_manual_override=mark_manual_override,
        )

    # ---- Automation and temporary pause ----

    def set_schedule(
        self,
        enabled: bool,
        *,
        mode: str | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
        city: str | None = None,
        on_time: str | None = None,
        off_time: str | None = None,
        days=None,
        day_profile: str | None = None,
        night_profile: str | None = None,
        sunrise_offset: int | None = None,
        sunset_offset: int | None = None,
    ) -> bool:
        enabled = bool(enabled)
        selected_mode = mode or self._settings.schedule_mode
        if selected_mode not in {"sun", "fixed"}:
            self.operation_failed.emit(
                "schedule_mode", "请选择固定时间或日出日落自动化。"
            )
            return False
        if (latitude is None) != (longitude is None):
            self.operation_failed.emit(
                "schedule_location", "纬度和经度必须同时填写。"
            )
            return False
        if latitude is not None and not (-90 <= float(latitude) <= 90):
            self.operation_failed.emit(
                "schedule_location", "纬度必须在 -90 到 90 之间。"
            )
            return False
        if longitude is not None and not (-180 <= float(longitude) <= 180):
            self.operation_failed.emit(
                "schedule_location", "经度必须在 -180 到 180 之间。"
            )
            return False
        if on_time is not None and not self._valid_clock_time(on_time):
            self.operation_failed.emit(
                "schedule_time", "开启时间格式无效，请使用 HH:MM。"
            )
            return False
        if off_time is not None and not self._valid_clock_time(off_time):
            self.operation_failed.emit(
                "schedule_time", "关闭时间格式无效，请使用 HH:MM。"
            )
            return False
        selected_days = None if days is None else tuple(sorted(set(days)))
        if selected_days is not None and (
            not selected_days
            or any(not isinstance(day, int) or day < 0 or day > 6 for day in selected_days)
        ):
            self.operation_failed.emit(
                "schedule_days", "请至少选择一个有效执行日。"
            )
            return False
        location_configured = self._settings.location_configured or latitude is not None
        if enabled and selected_mode == "sun" and not location_configured:
            self.operation_failed.emit(
                "schedule_location", "请先设置自动化位置。"
            )
            return False

        from opencareyes.config.presets import PRESETS

        selected_day_profile = day_profile or getattr(
            self._settings, "schedule_day_profile", "office"
        )
        selected_night_profile = night_profile or getattr(
            self._settings, "schedule_night_profile", "night"
        )
        if selected_day_profile not in PRESETS or selected_night_profile not in PRESETS:
            self.operation_failed.emit(
                "schedule_profile", "请选择有效的日间和夜间显示方案。"
            )
            return False
        for name, value in (
            ("sunrise", sunrise_offset),
            ("sunset", sunset_offset),
        ):
            if value is not None and not -120 <= int(value) <= 120:
                self.operation_failed.emit(
                    "schedule_offset",
                    "日出和日落偏移必须在 -120 到 120 分钟之间。",
                )
                return False

        def operation() -> None:
            self._require_service(self._scheduler, "scheduler")
            self._settings.schedule_mode = selected_mode
            if latitude is not None:
                self._settings.latitude = float(latitude)
                self._settings.longitude = float(longitude)
                if city is not None:
                    self._settings.city = str(city).strip()
                self._settings.location_configured = True
            if on_time is not None:
                self._settings.schedule_on_time = on_time
            if off_time is not None:
                self._settings.schedule_off_time = off_time
            if selected_days is not None:
                self._settings.schedule_days = selected_days
            if hasattr(self._settings, "schedule_day_profile"):
                self._settings.schedule_day_profile = selected_day_profile
            if hasattr(self._settings, "schedule_night_profile"):
                self._settings.schedule_night_profile = selected_night_profile
            if sunrise_offset is not None and hasattr(self._settings, "sunrise_offset"):
                self._settings.sunrise_offset = int(sunrise_offset)
            if sunset_offset is not None and hasattr(self._settings, "sunset_offset"):
                self._settings.sunset_offset = int(sunset_offset)
            self._settings.filter_schedule_enabled = enabled
            if enabled:
                self._scheduler.start(defer_apply=True)
            else:
                self._scheduler.stop()

        return self._run_schedule_update(
            "schedule",
            operation,
            apply_current_profile=enabled,
        )

    def undo_break_snooze(self) -> bool:
        def operation() -> None:
            self._require_service(self._break_reminder, "break reminder")
            undo = getattr(self._break_reminder, "undo_snooze", None)
            if not callable(undo) or not undo():
                raise RuntimeError("当前没有可撤销的稍后提醒")

        return self._run(
            "break_snooze_undo",
            operation,
            reconcile=False,
        )

    def recheck_display_capabilities(self) -> bool:
        """Request a non-blocking display capability refresh."""

        return self._run(
            "display_recheck",
            lambda: self._require_and_call(
                self._blue_filter,
                "refresh_screens",
            ),
            reconcile=False,
            persist_settings=False,
        )

    def restore_display_effects(self) -> bool:
        """Restore the original display and disable related preferences."""
        proposal = replace(
            self._current_display_state(),
            filter_enabled=False,
            dimmer_enabled=False,
            preset="custom",
        )
        return self._start_display_transaction(
            "display_restore_original",
            proposal,
            disable_focus=True,
            mark_manual_override=True,
        )

    def pause_all(
        self,
        minutes: int | None = None,
        *,
        until_next_schedule: bool = False,
    ) -> bool:
        if minutes is not None and until_next_schedule:
            self.operation_failed.emit(
                "global_pause", "暂停方式只能选择时长或直到下次自动切换。"
            )
            return False
        if minutes is not None and int(minutes) <= 0:
            self.operation_failed.emit(
                "global_pause", "暂停时长必须大于 0 分钟。"
            )
            return False
        if until_next_schedule and (
            self._scheduler is None or not self._scheduler.running
        ):
            self.operation_failed.emit(
                "global_pause", "自动化未运行，无法暂停到下次自动切换。"
            )
            return False

        mode = "next_schedule" if until_next_schedule else (
            "timed" if minutes is not None else "manual"
        )
        until_timestamp: float | None = None
        if minutes is not None:
            until_timestamp = time.time() + int(minutes) * 60

        return self._start_pause_transaction(
            "global_pause",
            mode,
            until_timestamp,
        )

    def resume_all(self) -> bool:
        return self._start_pause_transaction(
            "global_resume",
            "none",
            None,
        )

    # ---- Focus session and general settings ----

    def start_focus_session(self, minutes: int) -> bool:
        minutes = int(minutes)
        if minutes <= 0:
            self.operation_failed.emit(
                "focus_session", "专注时长必须大于 0 分钟。"
            )
            return False
        if not self.set_focus_enabled(True):
            return False
        self._focus_session_ends_at = datetime.now().astimezone() + timedelta(
            minutes=minutes
        )
        self._focus_timer.start(min(minutes * 60_000, 2_147_483_647))
        self.refresh_state()
        return True

    def set_theme(self, theme: str) -> bool:
        if theme not in {"system", "light", "dark"}:
            self.operation_failed.emit(
                "theme", "请选择跟随系统、亮色或暗色主题。"
            )
            return False
        return self._run("theme", lambda: setattr(self._settings, "theme", theme))

    def set_motion_mode(self, mode: str) -> bool:
        if mode not in {"system", "standard", "reduced"}:
            self.operation_failed.emit(
                "motion_mode", "请选择跟随系统、标准或减少动画。"
            )
            return False
        return self._run(
            "motion_mode",
            lambda: setattr(self._settings, "motion_mode", mode),
        )

    def set_pet_position(self, x: int, y: int) -> bool:
        x, y = int(x), int(y)

        def operation() -> None:
            self._settings.pet_x = x
            self._settings.pet_y = y

        return self._run("pet_position", operation, reconcile=False)

    def reset_pet_position(self) -> bool:
        def operation() -> None:
            self._settings.pet_x = None
            self._settings.pet_y = None

        return self._run("pet_position", operation, reconcile=False)

    def set_smart_pause_enabled(self, enabled: bool) -> bool:
        return self._set_context_preference("smart_pause_enabled", bool(enabled))

    def set_fullscreen_pause_enabled(self, enabled: bool) -> bool:
        return self._set_context_preference(
            "fullscreen_pause_enabled", bool(enabled)
        )

    def set_natural_rest_enabled(self, enabled: bool) -> bool:
        return self._set_context_preference("natural_rest_enabled", bool(enabled))

    def upsert_app_rule(self, rule) -> bool:
        def operation() -> None:
            updater = getattr(self._settings, "upsert_app_rule", None)
            if not callable(updater):
                raise RuntimeError("Application rules are unavailable")
            updater(rule)

        return self._run("app_rule", operation)

    def remove_app_rule(self, app_id: str) -> bool:
        def operation() -> None:
            remover = getattr(self._settings, "remove_app_rule", None)
            if not callable(remover):
                raise RuntimeError("Application rules are unavailable")
            remover(app_id)

        return self._run("app_rule", operation)

    def resume_breaks_for_current_context(self) -> bool:
        if self._context_runtime is None:
            self.operation_failed.emit(
                "context_override", "智能免打扰当前不可用。"
            )
            return False
        return bool(self._context_runtime.resume_breaks_for_current_context())

    def _set_context_preference(self, name: str, value: bool) -> bool:
        return self._run(
            name,
            lambda: setattr(self._settings, name, value),
        )

    def set_autostart(self, enabled: bool) -> bool:
        enabled = bool(enabled)

        def operation() -> None:
            from opencareyes.platform.autostart import (
                disable_autostart,
                enable_autostart,
            )

            if enabled:
                enable_autostart()
            else:
                disable_autostart()
            self._settings.autostart = enabled

        return self._run("autostart", operation)

    def set_location(
        self, latitude: float, longitude: float, city: str = ""
    ) -> bool:
        latitude = float(latitude)
        longitude = float(longitude)
        if not (-90 <= latitude <= 90) or not (-180 <= longitude <= 180):
            self.operation_failed.emit(
                "location", "纬度或经度超出有效范围。"
            )
            return False

        def operation() -> None:
            self._settings.latitude = latitude
            self._settings.longitude = longitude
            self._settings.city = city.strip()
            self._settings.location_configured = True
            if self._scheduler is not None and self._scheduler.running:
                self._scheduler.reschedule(defer_apply=True)

        return self._run_schedule_update(
            "location",
            operation,
            apply_current_profile=self._scheduler is not None,
        )

    def set_hotkey(self, action: str, sequence: str) -> bool:
        return self.set_hotkeys({action: sequence})

    def set_hotkeys(self, mapping) -> bool:
        """Validate and replace all affected shortcuts as one transaction."""

        if not isinstance(mapping, dict) or not mapping:
            self.operation_failed.emit("hotkey", "快捷键设置不能为空")
            return False
        properties = {
            "filter": "hotkey_filter",
            "break": "hotkey_break",
            "dimmer": "hotkey_dimmer",
            "focus": "hotkey_focus",
        }
        desired = {
            action: str(getattr(self._settings, property_name)).strip().lower()
            for action, property_name in properties.items()
        }
        previous = dict(desired)
        for raw_action, raw_sequence in mapping.items():
            action = str(raw_action).strip().lower()
            if action == "breaks":
                action = "break"
            if action not in properties:
                self.operation_failed.emit(
                    "hotkey", "不支持该快捷键功能。"
                )
                return False
            sequence = str(raw_sequence).strip().lower()
            if not sequence:
                self.operation_failed.emit("hotkey", "快捷键不能为空")
                return False
            desired[action] = sequence
        if len(set(desired.values())) != len(desired):
            self.operation_failed.emit("hotkey_conflict", "快捷键组合不能重复")
            return False

        callbacks = self._hotkey_callbacks()

        def operation() -> None:
            if self._hotkeys is not None and not self._hotkeys.replace_all(
                {
                    desired[action]: callbacks[action]
                    for action in properties
                }
            ):
                raise RuntimeError("无法注册新的快捷键组合")
            for action, property_name in properties.items():
                setattr(self._settings, property_name, desired[action])

        def rollback() -> None:
            if self._hotkeys is not None and not self._hotkeys.replace_all(
                {
                    previous[action]: callbacks[action]
                    for action in properties
                }
            ):
                raise RuntimeError("旧快捷键组合恢复失败")

        return self._run(
            "hotkey",
            operation,
            reconcile=False,
            rollback=rollback,
        )

    def reset_hotkeys(self) -> bool:
        defaults = {
            "filter": HOTKEY_TOGGLE_FILTER,
            "break": HOTKEY_TOGGLE_BREAK,
            "dimmer": HOTKEY_TOGGLE_DIMMER,
            "focus": HOTKEY_TOGGLE_FOCUS,
        }
        return self.set_hotkeys(defaults)

    def complete_onboarding(self) -> bool:
        return self._run(
            "onboarding",
            lambda: setattr(self._settings, "onboarding_completed", True),
        )

    def mark_onboarding_complete(self) -> bool:
        return self.complete_onboarding()

    def check_for_updates(self) -> bool:
        """Start the explicit GitHub check off the UI thread."""

        if self._update_state.status == "checking":
            return False
        if self._update_service is None:
            from opencareyes.application.update_service import ManualUpdateService

            self._update_service = ManualUpdateService()
        self._update_state = UpdateState("checking", APP_VERSION)
        self.refresh_state()
        worker = _UpdateWorker(self._update_service)
        self._update_workers[worker.signals] = worker
        worker.signals.finished.connect(
            self._on_update_finished,
            Qt.QueuedConnection,
        )
        QThreadPool.globalInstance().start(worker)
        return True

    @Slot(object)
    def _on_update_finished(self, state) -> None:
        sender = self.sender()
        if sender is not None:
            self._update_workers.pop(sender, None)
        if not isinstance(state, UpdateState):
            state = UpdateState("failed", APP_VERSION)
        self._update_state = state
        self.refresh_state()

    def export_diagnostics(self, path: str | Path) -> bool:
        destination = Path(path)
        state = self.refresh_state()
        return self._run(
            "diagnostics_export",
            lambda: write_diagnostics(destination, state),
        )

    def reset_settings(self) -> bool:
        def operation() -> None:
            self._pause_timer.stop()
            self._focus_timer.stop()
            self._focus_session_ends_at = None
            if self._scheduler is not None:
                self._scheduler.stop()
            if self._hotkeys is not None:
                self._hotkeys.unregister_all()
            self._settings.reset()
            self._restored = False

        return self._run("settings_reset", operation)

    # ---- Internal service orchestration ----

    def _on_scheduled_filter_state_requested(self, enabled: bool) -> None:
        self._clear_next_schedule_pause()
        profile = (
            getattr(self._settings, "schedule_night_profile", "night")
            if enabled
            else getattr(self._settings, "schedule_day_profile", "office")
        )
        self.apply_display_profile(profile, mark_manual_override=False)

    def _on_scheduled_profile_requested(self, profile: str) -> None:
        self._clear_next_schedule_pause()
        self.apply_display_profile(str(profile), mark_manual_override=False)

    def _clear_next_schedule_pause(self) -> None:
        mode, _until = self._current_pause_values()
        if (
            self._is_globally_paused()
            and mode == "next_schedule"
        ):
            self._start_pause_transaction(
                "global_resume",
                "none",
                None,
            )

    def _restore_configured_services(self, raise_errors: bool = False) -> bool:
        result = self._reconcile_effects()
        if result.succeeded:
            return True
        if raise_errors:
            raise RuntimeError(self._reconcile_error_message(result))

        setting_names = {
            "filter": ("filter_enabled", "restore_filter"),
            "dimmer": ("dimmer_enabled", "restore_dimmer"),
            "breaks": ("break_enabled", "restore_break"),
            "focus": ("focus_enabled", "restore_focus"),
        }
        for failure in result.failures:
            setting_name, code = setting_names.get(
                failure.feature,
                (None, "restore_effect"),
            )
            if setting_name is not None and bool(
                getattr(self._settings, setting_name, False)
            ):
                setattr(self._settings, setting_name, False)
            self._fail(code, failure.message)
        self._sync_settings_checked()
        self._reconcile_effects()
        return False

    def _disable_effects_for_pause(self, raise_errors: bool = False) -> bool:
        result = self._reconcile_effects()
        if not result.succeeded and raise_errors:
            raise RuntimeError(self._reconcile_error_message(result))
        return result.succeeded

    @staticmethod
    def _require_service(service, name: str) -> None:
        if service is None:
            raise RuntimeError(f"{name} is unavailable")

    @classmethod
    def _require_and_call(cls, service, method: str, *args) -> object:
        cls._require_service(service, method)
        result = getattr(service, method)(*args)
        if result is False:
            raise RuntimeError(f"{method} failed")
        return result

    def _settings_display_state(self) -> DisplayState:
        return DisplayState(
            filter_enabled=bool(self._settings.filter_enabled),
            color_temperature=int(self._settings.color_temperature),
            dimmer_enabled=bool(self._settings.dimmer_enabled),
            dim_level=int(self._settings.dim_level),
            preset=str(self._settings.current_preset),
        )

    def _settings_pause_values(self) -> tuple[str, float | None]:
        return (
            str(self._settings.global_pause_mode),
            self._settings.global_pause_until,
        )

    @staticmethod
    def _pause_values_active(
        mode: str,
        until: float | None,
    ) -> bool:
        if mode == "timed":
            return until is not None and until > time.time()
        return mode in {"manual", "next_schedule"}

    def _current_pause_values(self) -> tuple[str, float | None]:
        transaction = self._runtime_transaction
        if transaction is not None and transaction.owns_pause:
            return (
                transaction.proposal_pause_mode,
                transaction.proposal_pause_until,
            )
        return self._settings_pause_values()

    def _transaction_pause_state(
        self,
        transaction: _RuntimeTransaction,
    ) -> GlobalPauseState:
        mode = transaction.proposal_pause_mode
        until = transaction.proposal_pause_until
        active = self._pause_values_active(mode, until)
        until_datetime = (
            datetime.fromtimestamp(until).astimezone()
            if active and until is not None
            else None
        )
        return GlobalPauseState(
            active=active,
            mode=mode if active else "none",
            until=until_datetime,
        )

    def _current_display_state(self) -> DisplayState:
        transaction = self._runtime_transaction
        if transaction is not None:
            return transaction.proposal
        return self._settings_display_state()

    @staticmethod
    def _display_profile_state(name: str) -> DisplayState:
        from opencareyes.config.presets import PRESETS

        preset = PRESETS[str(name)]
        temperature = max(TEMP_MIN, min(TEMP_MAX, int(preset["temp"])))
        dim_level = max(DIM_MIN, min(DIM_MAX, int(preset["dim"])))
        return DisplayState(
            filter_enabled=True,
            color_temperature=temperature,
            dimmer_enabled=dim_level > 0,
            dim_level=dim_level,
            preset=str(name),
        )

    def _desired_for_display(
        self,
        display: DisplayState,
        *,
        focus_enabled: bool | None = None,
    ) -> DesiredEffectState:
        return DesiredEffectState(
            filter=bool(display.filter_enabled),
            dimmer=bool(display.dimmer_enabled),
            breaks=bool(self._settings.break_enabled),
            focus=(
                bool(self._settings.focus_enabled)
                if focus_enabled is None
                else bool(focus_enabled)
            ),
            color_temperature=int(display.color_temperature),
            dim_level=int(display.dim_level),
            focus_dim_level=int(self._settings.focus_dim_level),
        )

    def _preview_display(
        self,
        code: str,
        preview: DisplayPreview,
    ) -> bool:
        desired = self._desired_for_display(self._current_display_state())
        self._in_transaction = True
        try:
            result = self._reconcile_effects(
                preview=preview,
                desired=desired,
                display_revision=self._runtime_revision,
                display_purpose="preview",
            )
        except Exception as exc:
            self._in_transaction = False
            self._fail(code, exc)
            self.refresh_state(force=True)
            return False
        self._in_transaction = False
        if not result.succeeded:
            self._fail(code, self._reconcile_error_message(result))
            self.refresh_state(force=True)
            return False
        self.refresh_state()
        return True

    def _start_display_transaction(
        self,
        code: str,
        proposal: DisplayState,
        *,
        disable_focus: bool = False,
        mark_manual_override: bool = False,
        settings_snapshot: object | None = None,
        scheduler_snapshot: object | None = None,
        settings_proposal: object | None = None,
        scheduler_proposal: object | None = None,
    ) -> bool:
        baseline = self._settings_display_state()
        desired = self._desired_for_display(proposal)
        previous = self._runtime_transaction
        if settings_snapshot is None and previous is not None:
            settings_snapshot = previous.settings_snapshot
            scheduler_snapshot = previous.scheduler_snapshot
            settings_proposal = previous.settings_proposal
            scheduler_proposal = previous.scheduler_proposal
        settings_pause_mode, settings_pause_until = (
            self._settings_pause_values()
        )
        baseline_pause_mode = (
            previous.baseline_pause_mode
            if previous is not None and previous.owns_pause
            else settings_pause_mode
        )
        baseline_pause_until = (
            previous.baseline_pause_until
            if previous is not None and previous.owns_pause
            else settings_pause_until
        )
        proposal_pause_mode = (
            previous.proposal_pause_mode
            if previous is not None and previous.owns_pause
            else settings_pause_mode
        )
        proposal_pause_until = (
            previous.proposal_pause_until
            if previous is not None and previous.owns_pause
            else settings_pause_until
        )
        scheduler_running = bool(
            self._scheduler is not None and self._scheduler.running
        )
        scheduler_running = scheduler_running or self._scheduler_snapshot_running(
            scheduler_proposal
        )
        inherit_override = bool(
            previous is not None
            and previous.manual_override_claimed
        )
        claim_override = inherit_override or bool(
            mark_manual_override and scheduler_running
        )
        if claim_override and scheduler_proposal is not None:
            scheduler_proposal = self._scheduler_snapshot_with_override(
                scheduler_proposal,
                True,
            )
        override_baseline = (
            previous.manual_override_baseline
            if inherit_override and previous is not None
            else bool(getattr(self._scheduler, "manual_override", False))
        )
        self._runtime_revision += 1
        transaction = _RuntimeTransaction(
            revision=self._runtime_revision,
            code=code,
            baseline=baseline,
            proposal=proposal,
            desired=desired,
            baseline_pause_mode=baseline_pause_mode,
            baseline_pause_until=baseline_pause_until,
            proposal_pause_mode=proposal_pause_mode,
            proposal_pause_until=proposal_pause_until,
            owns_display=True,
            owns_pause=bool(previous is not None and previous.owns_pause),
            disable_focus=bool(
                disable_focus
                or (previous is not None and previous.disable_focus)
            ),
            manual_override_claimed=claim_override,
            manual_override_baseline=override_baseline,
            settings_snapshot=settings_snapshot,
            scheduler_snapshot=scheduler_snapshot,
            settings_proposal=settings_proposal,
            scheduler_proposal=scheduler_proposal,
        )
        return self._apply_runtime_transaction(
            transaction,
            force_display_commit=True,
        )

    def _start_pause_transaction(
        self,
        code: str,
        mode: str,
        until: float | None,
    ) -> bool:
        previous = self._runtime_transaction
        settings_display = self._settings_display_state()
        settings_pause_mode, settings_pause_until = (
            self._settings_pause_values()
        )
        baseline_display = (
            previous.baseline
            if previous is not None and previous.owns_display
            else settings_display
        )
        proposal_display = (
            previous.proposal
            if previous is not None and previous.owns_display
            else settings_display
        )
        baseline_pause_mode = (
            previous.baseline_pause_mode
            if previous is not None and previous.owns_pause
            else settings_pause_mode
        )
        baseline_pause_until = (
            previous.baseline_pause_until
            if previous is not None and previous.owns_pause
            else settings_pause_until
        )
        inherit_override = bool(
            previous is not None
            and previous.manual_override_claimed
        )
        self._runtime_revision += 1
        transaction = _RuntimeTransaction(
            revision=self._runtime_revision,
            code=code,
            baseline=baseline_display,
            proposal=proposal_display,
            desired=self._desired_for_display(proposal_display),
            baseline_pause_mode=baseline_pause_mode,
            baseline_pause_until=baseline_pause_until,
            proposal_pause_mode=str(mode),
            proposal_pause_until=until,
            owns_display=bool(
                previous is not None and previous.owns_display
            ),
            owns_pause=True,
            disable_focus=bool(
                previous is not None and previous.disable_focus
            ),
            manual_override_claimed=inherit_override,
            manual_override_baseline=(
                previous.manual_override_baseline
                if inherit_override and previous is not None
                else bool(
                    getattr(self._scheduler, "manual_override", False)
                )
            ),
            settings_snapshot=(
                previous.settings_snapshot
                if previous is not None
                else None
            ),
            scheduler_snapshot=(
                previous.scheduler_snapshot
                if previous is not None
                else None
            ),
            settings_proposal=(
                previous.settings_proposal
                if previous is not None
                else None
            ),
            scheduler_proposal=(
                previous.scheduler_proposal
                if previous is not None
                else None
            ),
        )
        return self._apply_runtime_transaction(
            transaction,
            force_display_commit=transaction.owns_display,
        )

    def _apply_runtime_transaction(
        self,
        transaction: _RuntimeTransaction,
        *,
        force_display_commit: bool,
    ) -> bool:
        # Replacing the staged transaction is intentional. Its native request
        # remains serialized, but only this latest revision may commit settings.
        self._runtime_transaction = transaction
        self._in_transaction = True
        try:
            if (
                transaction.manual_override_claimed
                and self._scheduler is not None
                and bool(getattr(self._scheduler, "running", False))
            ):
                self._scheduler.set_manual_override(True)
            result = self._reconcile_effects(
                desired=transaction.desired,
                global_pause=self._pause_values_active(
                    transaction.proposal_pause_mode,
                    transaction.proposal_pause_until,
                ),
                display_revision=transaction.revision,
                display_purpose="commit",
                force_display_commit=force_display_commit,
            )
        except Exception as exc:
            self._in_transaction = False
            return self._abort_runtime_transaction(transaction, exc)
        self._in_transaction = False
        if not result.succeeded:
            return self._abort_runtime_transaction(
                transaction,
                self._reconcile_error_message(result),
            )

        if transaction.request_ids:
            self.refresh_state(force=True)
            return True
        return self._commit_runtime_transaction(transaction)

    def _commit_runtime_transaction(
        self,
        transaction: _RuntimeTransaction,
    ) -> bool:
        if self._runtime_transaction is not transaction:
            return False
        self._in_transaction = True
        focus_before_commit = bool(self._settings.focus_enabled)
        try:
            if (
                transaction.owns_pause
                and transaction.proposal_pause_mode == "timed"
                and (
                    transaction.proposal_pause_until is None
                    or transaction.proposal_pause_until <= time.time()
                )
            ):
                transaction.proposal_pause_mode = "none"
                transaction.proposal_pause_until = None
                transaction.desired = self._desired_for_display(
                    transaction.proposal
                )
                result = self._reconcile_effects(
                    desired=transaction.desired,
                    global_pause=False,
                    display_revision=transaction.revision,
                    display_purpose="commit",
                    force_display_commit=transaction.owns_display,
                )
                if not result.succeeded:
                    raise RuntimeError(
                        self._reconcile_error_message(result)
                    )
                if transaction.request_ids:
                    self._in_transaction = False
                    self.refresh_state(force=True)
                    return True
            if transaction.disable_focus:
                transaction.desired = replace(
                    transaction.desired,
                    focus=False,
                )
                result = self._reconcile_effects(
                    desired=transaction.desired,
                    display_revision=transaction.revision,
                    display_purpose="commit",
                )
                if not result.succeeded:
                    raise RuntimeError(
                        self._reconcile_error_message(result)
                    )
                if transaction.request_ids:
                    self._in_transaction = False
                    self.refresh_state(force=True)
                    return True
            if isinstance(
                transaction.settings_proposal,
                _OwnedSettingsSnapshot,
            ):
                self._apply_owned_settings_unchecked(
                    transaction.settings_proposal
                )
            if transaction.scheduler_proposal is not None:
                self._restore_scheduler_runtime(
                    transaction.scheduler_proposal
                )
            if transaction.owns_display:
                self._write_display_settings(transaction.proposal)
            if transaction.owns_pause:
                self._settings.global_pause_mode = (
                    transaction.proposal_pause_mode
                )
                self._settings.global_pause_until = (
                    transaction.proposal_pause_until
                )
            if transaction.disable_focus:
                self._settings.focus_enabled = False
            self._sync_settings_checked()
        except Exception as exc:
            rollback_errors = self._restore_runtime_preferences(
                transaction,
                focus_enabled=focus_before_commit,
            )
            self._in_transaction = False
            return self._abort_runtime_transaction(
                transaction,
                exc,
                rollback_errors=rollback_errors,
            )

        if transaction.disable_focus:
            self._focus_timer.stop()
            self._focus_session_ends_at = None
        if transaction.owns_pause:
            self._pause_timer.stop()
            self._restore_pause_deadline()
        self._runtime_transaction = None
        self._clear_runtime_override()
        try:
            follow_up = self._reconcile_effects()
        except Exception as exc:
            self._fail("display_post_commit", exc)
        else:
            if not follow_up.succeeded:
                self._fail(
                    "display_post_commit",
                    self._reconcile_error_message(follow_up),
                )
        self._in_transaction = False
        self.refresh_state(force=True)
        return True

    def _abort_runtime_transaction(
        self,
        transaction: _RuntimeTransaction,
        error: Exception | str,
        *,
        rollback_errors: list[str] | None = None,
    ) -> bool:
        errors = list(rollback_errors or ())
        if self._runtime_transaction is not transaction:
            return False
        self._in_transaction = True
        self._runtime_transaction = None
        self._clear_runtime_override()
        if (
            transaction.settings_snapshot is not None
            and not transaction.owned_configuration_restored
        ):
            errors.extend(
                self._restore_owned_configuration(
                    transaction.settings_snapshot,
                    transaction.scheduler_snapshot,
                )
            )
            transaction.owned_configuration_restored = True
        if (
            transaction.manual_override_claimed
            and self._scheduler is not None
        ):
            try:
                self._scheduler.set_manual_override(
                    transaction.manual_override_baseline
                )
            except Exception as exc:
                errors.append(str(exc))
        compensation = self._compensate_runtime(transaction)
        if compensation:
            errors.extend(compensation)
        self._in_transaction = False
        self._fail(transaction.code, error)
        if errors:
            self._fail(
                f"{transaction.code}_rollback",
                "设置或效果回滚不完整：" + "; ".join(errors),
            )
        self.refresh_state(force=True)
        return False

    def _compensate_runtime(
        self,
        transaction: _RuntimeTransaction,
    ) -> list[str]:
        errors: list[str] = []
        self._runtime_revision += 1
        try:
            result = self._reconcile_effects(
                desired=self._desired_for_display(transaction.baseline),
                global_pause=self._pause_values_active(
                    transaction.baseline_pause_mode,
                    transaction.baseline_pause_until,
                ),
                display_revision=self._runtime_revision,
                display_purpose="compensation",
                force_display_commit=True,
            )
            if not result.succeeded:
                errors.append(self._reconcile_error_message(result))
            for request in result.pending_requests:
                request_id = getattr(request, "request_id", None)
                if request_id is not None:
                    self._runtime_compensation_ids[int(request_id)] = (
                        transaction.code
                    )
        except Exception as exc:
            errors.append(str(exc))
        finally:
            self._clear_runtime_override()
        try:
            follow_up = self._reconcile_effects()
            if not follow_up.succeeded:
                errors.append(self._reconcile_error_message(follow_up))
        except Exception as exc:
            errors.append(str(exc))
        return errors

    def _write_display_settings(self, display: DisplayState) -> None:
        self._settings.filter_enabled = bool(display.filter_enabled)
        self._settings.color_temperature = int(display.color_temperature)
        self._settings.dimmer_enabled = bool(display.dimmer_enabled)
        self._settings.dim_level = int(display.dim_level)
        self._settings.current_preset = str(display.preset)

    def _restore_runtime_preferences(
        self,
        transaction: _RuntimeTransaction,
        *,
        focus_enabled: bool,
    ) -> list[str]:
        errors: list[str] = []
        if transaction.settings_snapshot is not None:
            try:
                if transaction.owns_display:
                    self._write_display_settings(transaction.baseline)
                if transaction.owns_pause:
                    self._settings.global_pause_mode = (
                        transaction.baseline_pause_mode
                    )
                    self._settings.global_pause_until = (
                        transaction.baseline_pause_until
                    )
                if transaction.disable_focus:
                    self._settings.focus_enabled = bool(focus_enabled)
            except Exception as exc:
                errors.append(str(exc))
            errors.extend(
                self._restore_owned_configuration(
                    transaction.settings_snapshot,
                    transaction.scheduler_snapshot,
                )
            )
            transaction.owned_configuration_restored = True
            return errors
        try:
            if transaction.owns_display:
                self._write_display_settings(transaction.baseline)
            if transaction.owns_pause:
                self._settings.global_pause_mode = (
                    transaction.baseline_pause_mode
                )
                self._settings.global_pause_until = (
                    transaction.baseline_pause_until
                )
            if transaction.disable_focus:
                self._settings.focus_enabled = bool(focus_enabled)
            self._sync_settings_checked()
        except Exception as exc:
            errors.append(str(exc))
        return errors

    def _clear_runtime_override(self) -> None:
        clear = getattr(self._context_runtime, "clear_runtime_override", None)
        if not callable(clear):
            clear = getattr(
                self._context_runtime,
                "clear_display_override",
                None,
            )
        if callable(clear):
            clear()

    def _run_schedule_update(
        self,
        code: str,
        operation: Callable[[], object],
        *,
        apply_current_profile: bool,
    ) -> bool:
        """Stage automation outside QSettings until its display is verified."""

        previous = self._runtime_transaction
        settings_snapshot = (
            previous.settings_snapshot
            if previous is not None and previous.settings_snapshot is not None
            else self._snapshot_owned_settings(_SCHEDULE_SETTING_KEYS)
        )
        scheduler_snapshot = (
            previous.scheduler_snapshot
            if previous is not None and previous.scheduler_snapshot is not None
            else self._snapshot_scheduler_runtime()
        )
        settings_base = (
            previous.settings_proposal
            if previous is not None
            and isinstance(
                previous.settings_proposal,
                _OwnedSettingsSnapshot,
            )
            else settings_snapshot
        )
        scheduler_base = (
            previous.scheduler_proposal
            if previous is not None
            and previous.scheduler_proposal is not None
            else scheduler_snapshot
        )
        self._apply_owned_settings_unchecked(settings_base)
        if scheduler_base is not None:
            self._restore_scheduler_runtime(scheduler_base)

        operation_error: Exception | None = None
        restore_errors: list[str] = []
        settings_proposal = None
        scheduler_proposal = None
        profile = ""
        self._in_transaction = True
        try:
            operation()
            settings_proposal = self._snapshot_owned_settings(
                _SCHEDULE_SETTING_KEYS
            )
            scheduler_proposal = self._snapshot_scheduler_runtime()
            if (
                apply_current_profile
                and self._scheduler is not None
                and bool(getattr(self._scheduler, "running", False))
            ):
                profile = str(
                    getattr(self._scheduler, "current_profile", "") or ""
                )
        except Exception as exc:
            operation_error = exc
        finally:
            try:
                self._apply_owned_settings_unchecked(settings_snapshot)
            except Exception as exc:
                restore_errors.append(str(exc))
            try:
                if scheduler_snapshot is not None:
                    self._restore_scheduler_runtime(scheduler_snapshot)
            except Exception as exc:
                restore_errors.append(str(exc))
            self._in_transaction = False
        if operation_error is not None or restore_errors:
            self._fail(
                code,
                operation_error or "自动化暂存状态恢复失败",
            )
            if restore_errors:
                self._fail(
                    f"{code}_rollback",
                    "自动化设置或运行状态回滚不完整："
                    + "; ".join(restore_errors),
                )
            self.refresh_state(force=True)
            return False
        if not isinstance(settings_proposal, _OwnedSettingsSnapshot):
            self._fail(code, "无法暂存自动化设置")
            self.refresh_state(force=True)
            return False

        if not profile:
            if (
                previous is not None
                and previous.settings_proposal is not None
                and previous.owns_display
            ):
                return self._start_display_transaction(
                    code,
                    previous.baseline,
                    mark_manual_override=False,
                    settings_snapshot=settings_snapshot,
                    scheduler_snapshot=scheduler_snapshot,
                    settings_proposal=settings_proposal,
                    scheduler_proposal=scheduler_proposal,
                )
            self._in_transaction = True
            try:
                self._apply_owned_settings_unchecked(settings_proposal)
                if scheduler_proposal is not None:
                    self._restore_scheduler_runtime(scheduler_proposal)
                self._sync_settings_checked()
            except Exception as exc:
                rollback_errors = self._restore_owned_configuration(
                    settings_snapshot,
                    scheduler_snapshot,
                )
                self._in_transaction = False
                self._fail(code, exc)
                if rollback_errors:
                    self._fail(
                        f"{code}_rollback",
                        "自动化设置或运行状态回滚不完整："
                        + "; ".join(rollback_errors),
                    )
                self.refresh_state(force=True)
                return False
            self._in_transaction = False
            self.refresh_state()
            return True
        try:
            proposal = self._display_profile_state(profile)
            self._require_service(self._blue_filter, "blue-light filter")
            if proposal.dim_level > 0:
                self._require_service(self._dimmer, "screen dimmer")
        except Exception as exc:
            rollback_errors = self._restore_owned_configuration(
                settings_snapshot,
                scheduler_snapshot,
            )
            self._fail(code, exc)
            if rollback_errors:
                self._fail(
                    f"{code}_rollback",
                    "自动化设置或运行状态回滚不完整："
                    + "; ".join(rollback_errors),
                )
            self.refresh_state(force=True)
            return False
        return self._start_display_transaction(
            code,
            proposal,
            mark_manual_override=False,
            settings_snapshot=settings_snapshot,
            scheduler_snapshot=scheduler_snapshot,
            settings_proposal=settings_proposal,
            scheduler_proposal=scheduler_proposal,
        )

    def _snapshot_scheduler_runtime(self):
        scheduler = self._scheduler
        if scheduler is None:
            return None
        snapshot = getattr(scheduler, "snapshot_runtime", None)
        if callable(snapshot):
            return snapshot()
        return {
            "running": bool(getattr(scheduler, "running", False)),
            "manual_override": bool(
                getattr(scheduler, "manual_override", False)
            ),
            "current_profile": getattr(scheduler, "current_profile", None),
            "next_event": getattr(scheduler, "next_event", None),
            "next_event_at": getattr(scheduler, "next_event_at", None),
            "next_profile": getattr(scheduler, "next_profile", None),
        }

    @staticmethod
    def _scheduler_snapshot_running(snapshot) -> bool:
        if isinstance(snapshot, dict):
            return bool(snapshot.get("running", False))
        return bool(getattr(snapshot, "running", False))

    @staticmethod
    def _scheduler_snapshot_with_override(snapshot, enabled: bool):
        if isinstance(snapshot, dict):
            updated = dict(snapshot)
            updated["manual_override"] = bool(enabled)
            return updated
        return replace(snapshot, manual_override=bool(enabled))

    def _restore_owned_configuration(
        self,
        settings_snapshot,
        scheduler_snapshot,
    ) -> list[str]:
        errors: list[str] = []
        try:
            self._restore_settings_snapshot(settings_snapshot)
        except Exception as exc:
            errors.append(str(exc))
        scheduler = self._scheduler
        if scheduler is None or scheduler_snapshot is None:
            return errors
        try:
            self._restore_scheduler_runtime(scheduler_snapshot)
        except Exception as exc:
            errors.append(str(exc))
        return errors

    def _restore_scheduler_runtime(self, snapshot) -> None:
        scheduler = self._scheduler
        if scheduler is None or snapshot is None:
            return
        restore = getattr(scheduler, "restore_runtime", None)
        if callable(restore):
            restore(snapshot)
            return
        if isinstance(snapshot, dict):
            for name, value in snapshot.items():
                private_name = f"_{name}"
                if hasattr(scheduler, private_name):
                    setattr(scheduler, private_name, value)
                elif hasattr(scheduler, name):
                    setattr(scheduler, name, value)

    def _run(
        self,
        code: str,
        operation: Callable[[], object],
        *,
        preview: DisplayPreview | None = None,
        reconcile: bool = True,
        rollback: Callable[[], object] | None = None,
        persist_settings: bool = True,
    ) -> bool:
        snapshot = self._snapshot_settings() if persist_settings else None
        self._in_transaction = True
        try:
            operation()
            if reconcile:
                result = self._reconcile_effects(preview=preview)
                if not result.succeeded:
                    raise RuntimeError(self._reconcile_error_message(result))
            if persist_settings:
                self._sync_settings_checked()
        except Exception as exc:
            rollback_errors: list[str] = []
            if persist_settings:
                try:
                    self._restore_settings_snapshot(snapshot)
                except Exception as rollback_exc:
                    rollback_errors.append(str(rollback_exc))
            if rollback is not None:
                try:
                    rollback()
                except Exception as rollback_exc:
                    rollback_errors.append(str(rollback_exc))
            try:
                self._apply_break_configuration_from_settings()
            except Exception as rollback_exc:
                rollback_errors.append(str(rollback_exc))
            if reconcile:
                rollback_result = self._reconcile_effects()
                if not rollback_result.succeeded:
                    rollback_errors.append(
                        self._reconcile_error_message(rollback_result)
                    )
            self._restore_pause_deadline()
            self._in_transaction = False
            self._fail(code, exc)
            if rollback_errors:
                self._fail(
                    f"{code}_rollback",
                    "设置或效果回滚不完整：" + "; ".join(rollback_errors),
                )
            # Republish even when persistence is unchanged so controls that
            # optimistically toggled themselves are restored in this event loop.
            self.refresh_state(force=True)
            return False
        self._in_transaction = False
        self.refresh_state()
        return True

    def _reconcile_effects(
        self,
        *,
        preview: DisplayPreview | None = None,
        desired: DesiredEffectState | None = None,
        global_pause: bool | None = None,
        display_revision: int | None = None,
        display_purpose: str | None = None,
        force_display_commit: bool = False,
    ) -> ReconcileResult:
        transaction = self._runtime_transaction
        if desired is None and transaction is not None:
            desired = self._desired_for_display(
                transaction.proposal
            )
            transaction.desired = desired
        if global_pause is None and transaction is not None:
            global_pause = self._pause_values_active(
                transaction.proposal_pause_mode,
                transaction.proposal_pause_until,
            )
        if transaction is not None and display_revision is None:
            display_revision = transaction.revision
            display_purpose = "commit"
        if self._context_runtime is not None:
            self._context_runtime.recompute(
                preview=preview,
                desired=desired,
                global_pause=global_pause,
                display_revision=display_revision,
                display_purpose=display_purpose,
                force_display_commit=force_display_commit,
            )
            result = getattr(self._context_runtime, "last_result", None)
            if isinstance(result, ReconcileResult):
                self._effective_policy = result.policy
                self._track_runtime_pending(result)
                return result
        result = self._effects.reconcile(
            self._effects.intent_from_settings(
                desired=desired,
                global_pause=global_pause,
                preview=preview,
            ),
            display_revision=(
                0 if display_revision is None else display_revision
            ),
            display_purpose=(
                "system" if display_purpose is None else display_purpose
            ),
            force_display_commit=force_display_commit,
        )
        self._effective_policy = result.policy
        self._track_runtime_pending(result)
        return result

    def _track_runtime_pending(self, result: ReconcileResult) -> None:
        transaction = self._runtime_transaction
        if transaction is None:
            return
        for request in result.pending_requests:
            if (
                int(getattr(request, "revision", -1))
                == transaction.revision
                and str(getattr(request, "purpose", "")) == "commit"
            ):
                request_id = getattr(request, "request_id", None)
                if request_id is not None:
                    identifier = int(request_id)
                    transaction.request_ids.add(identifier)
                    key = (
                        str(getattr(request, "feature", "filter")),
                        str(getattr(request, "purpose", "commit")),
                    )
                    transaction.latest_request_ids[key] = max(
                        identifier,
                        transaction.latest_request_ids.get(key, 0),
                    )

    def _apply_break_configuration_from_settings(self) -> None:
        reminder = self._break_reminder
        if reminder is None:
            return
        set_style = getattr(reminder, "set_reminder_style", None)
        if callable(set_style):
            set_style(
                getattr(
                    self._settings,
                    "break_reminder_style",
                    "fullscreen",
                )
            )
        configure = getattr(reminder, "configure_cadence", None)
        if callable(configure):
            configure(
                mode=getattr(
                    self._settings,
                    "cadence_mode",
                    self._settings.break_mode,
                ),
                short_interval=getattr(
                    self._settings,
                    "cadence_short_interval",
                    self._settings.work_duration,
                ),
                short_duration=getattr(
                    self._settings,
                    "cadence_short_duration",
                    self._settings.break_duration,
                ),
                long_enabled=getattr(
                    self._settings, "cadence_long_enabled", False
                ),
                long_interval=getattr(
                    self._settings, "cadence_long_interval", 60 * 60
                ),
                long_duration=getattr(
                    self._settings, "cadence_long_duration", 5 * 60
                ),
            )
        else:
            reminder.set_mode(self._settings.break_mode)
            reminder.set_work_duration(self._settings.work_duration)
            reminder.set_break_duration(self._settings.break_duration)
        reminder.force_break = self._settings.force_break

    def _persist_break_configuration(self) -> None:
        reminder = self._break_reminder
        if reminder is None or not hasattr(self._settings, "cadence_mode"):
            return
        self._settings.cadence_mode = str(
            getattr(reminder, "mode", self._settings.break_mode)
        )
        self._settings.cadence_short_interval = int(
            getattr(reminder, "short_interval", self._settings.work_duration)
        )
        self._settings.cadence_short_duration = int(
            getattr(reminder, "short_duration", self._settings.break_duration)
        )
        self._settings.cadence_long_enabled = bool(
            getattr(reminder, "long_enabled", False)
        )
        self._settings.cadence_long_interval = int(
            getattr(reminder, "long_interval", 60 * 60)
        )
        self._settings.cadence_long_duration = int(
            getattr(reminder, "long_duration", 5 * 60)
        )

    @staticmethod
    def _reconcile_error_message(result: ReconcileResult) -> str:
        return "; ".join(
            f"{failure.feature}: {failure.message}"
            for failure in result.failures
        ) or "运行时效果未能应用"

    def _snapshot_settings(self):
        snapshot = getattr(self._settings, "snapshot", None)
        if callable(snapshot):
            return snapshot()
        store = getattr(self._settings, "_s", None)
        if store is None:
            return None
        return {
            str(key): store.value(key, None)
            for key in tuple(store.allKeys() or ())
        }

    def _snapshot_owned_settings(
        self,
        keys: tuple[str, ...],
    ) -> _OwnedSettingsSnapshot:
        snapshot = self._snapshot_settings() or {}
        return _OwnedSettingsSnapshot(
            keys=tuple(keys),
            values={key: snapshot[key] for key in keys if key in snapshot},
        )

    @staticmethod
    def _merge_owned_settings(
        current: dict[str, object],
        owned: _OwnedSettingsSnapshot,
    ) -> dict[str, object]:
        merged = dict(current)
        for key in owned.keys:
            merged.pop(key, None)
        merged.update(owned.values)
        return merged

    def _write_settings_snapshot_unchecked(
        self,
        snapshot: dict[str, object],
    ) -> bool:
        store = getattr(self._settings, "_s", None)
        if store is None:
            return False
        store.clear()
        for key, value in snapshot.items():
            store.setValue(key, value)
        return True

    def _apply_owned_settings_unchecked(
        self,
        snapshot: _OwnedSettingsSnapshot,
    ) -> None:
        if not isinstance(snapshot, _OwnedSettingsSnapshot):
            raise TypeError("owned settings snapshot is required")
        current = self._snapshot_settings() or {}
        merged = self._merge_owned_settings(current, snapshot)
        if not self._write_settings_snapshot_unchecked(merged):
            raise RuntimeError("设置后端不支持自动化暂存")

    def _restore_settings_snapshot(self, snapshot) -> None:
        if snapshot is None:
            return
        if isinstance(snapshot, _OwnedSettingsSnapshot):
            current = self._snapshot_settings() or {}
            snapshot = self._merge_owned_settings(current, snapshot)
        restore = getattr(self._settings, "restore_snapshot", None)
        if callable(restore):
            restore(snapshot)
            return
        store = getattr(self._settings, "_s", None)
        if store is None:
            return
        store.clear()
        for key, value in snapshot.items():
            store.setValue(key, value)
        self._sync_settings_checked()

    def _sync_settings_checked(self) -> None:
        self._sync_settings_backend_checked()

    def _sync_settings_backend_checked(self) -> None:
        sync_checked = getattr(self._settings, "sync_checked", None)
        if callable(sync_checked):
            sync_checked()
            return
        self._settings.sync()
        store = getattr(self._settings, "_s", None)
        status = getattr(store, "status", None)
        if callable(status):
            result = status()
            name = getattr(result, "name", "NoError")
            if (type(result) is int and result != 0) or name != "NoError":
                raise OSError(f"Settings backend sync failed: {result}")

    def _fail(self, code: str, error: Exception | str) -> None:
        detail = str(error) or error.__class__.__name__
        log.error("Operation failed [%s]: %s", code, detail)
        self.operation_failed.emit(code, _user_failure_message(code))

    def _restore_pause_deadline(self) -> bool:
        mode = self._settings.global_pause_mode
        until = self._settings.global_pause_until
        if mode == "timed":
            if until is None or until <= time.time():
                self._settings.global_pause_mode = "none"
                self._settings.global_pause_until = None
                return False
            milliseconds = max(1, int((until - time.time()) * 1000))
            self._pause_timer.start(min(milliseconds, 2_147_483_647))
            return True
        if mode in {"manual", "next_schedule"}:
            return True
        if mode != "none":
            self._settings.global_pause_mode = "none"
            self._settings.global_pause_until = None
        return False

    def _is_globally_paused(self) -> bool:
        mode, until = self._current_pause_values()
        return self._pause_values_active(mode, until)

    def _on_focus_session_timeout(self) -> None:
        self._focus_session_ends_at = None
        self.set_focus_enabled(False)

    def _register_hotkeys(self) -> bool:
        if self._hotkeys is None:
            return True
        callbacks = self._hotkey_callbacks()
        return self._hotkeys.replace_all(
            {
                self._settings.hotkey_filter: callbacks["filter"],
                self._settings.hotkey_break: callbacks["break"],
                self._settings.hotkey_dimmer: callbacks["dimmer"],
                self._settings.hotkey_focus: callbacks["focus"],
            }
        )

    def _hotkey_callbacks(self) -> dict[str, Callable[[], bool]]:
        return {
            "filter": lambda: self.set_filter_enabled(
                not self._settings.filter_enabled
            ),
            "break": lambda: self.set_break_enabled(
                not self._settings.break_enabled
            ),
            "dimmer": lambda: self.set_dimmer_enabled(
                not self._settings.dimmer_enabled
            ),
            "focus": lambda: self.set_focus_enabled(
                not self._settings.focus_enabled
            ),
        }

    def _on_effective_policy_changed(
        self,
        policy: EffectivePolicyState,
    ) -> None:
        self._effective_policy = policy
        if not self._in_transaction:
            self.refresh_state()

    @Slot(object)
    def _on_context_reconcile_completed(self, result) -> None:
        if isinstance(result, ReconcileResult):
            self._track_runtime_pending(result)

    @Slot(object)
    def _on_display_request_finished(self, result) -> None:
        request_id = int(getattr(result, "request_id", 0) or 0)
        compensation_code = self._runtime_compensation_ids.pop(
            request_id,
            None,
        )
        if compensation_code is not None:
            if (
                not bool(getattr(result, "success", False))
                and not bool(getattr(result, "superseded", False))
                and request_id >= int(
                    getattr(self._blue_filter, "last_request_id", 0) or 0
                )
            ):
                self._fail(
                    f"{compensation_code}_rollback",
                    getattr(result, "message", "显示效果补偿失败"),
                )
            self.refresh_state()
            return

        transaction = self._runtime_transaction
        if (
            transaction is not None
            and int(getattr(result, "revision", -1))
            == transaction.revision
            and request_id in transaction.request_ids
        ):
            key = (
                str(getattr(result, "feature", "filter")),
                str(getattr(result, "purpose", "commit")),
            )
            latest_request_id = transaction.latest_request_ids.get(
                key,
                request_id,
            )
            if request_id < latest_request_id:
                transaction.request_ids.discard(request_id)
                if not transaction.request_ids:
                    self._commit_runtime_transaction(transaction)
                else:
                    self.refresh_state()
                return
            if bool(getattr(result, "superseded", False)):
                self._abort_runtime_transaction(
                    transaction,
                    "显示提交已被更新的原生请求替代，偏好未保存",
                )
                return
            hdr_suppressed = (
                str(getattr(result, "code", "")) == "hdr_active"
                and bool(getattr(result, "hdr_active", False))
            )
            if (
                not bool(getattr(result, "success", False))
                and not hdr_suppressed
            ):
                self._abort_runtime_transaction(
                    transaction,
                    getattr(result, "message", "显示效果应用失败"),
                )
                return
            transaction.request_ids.discard(request_id)
            if not transaction.request_ids:
                self._commit_runtime_transaction(transaction)
            else:
                self.refresh_state()
            return

        purpose = str(getattr(result, "purpose", "system") or "system")
        # A commit from an older revision is intentionally silent: it must not
        # roll back or report against a newer accepted preference.
        if purpose in {"commit", "compensation"}:
            return
        latest_request_id = int(
            getattr(self._blue_filter, "last_request_id", 0) or 0
        )
        if (
            not bool(getattr(result, "success", False))
            and str(getattr(result, "code", "")) != "hdr_active"
            and not bool(getattr(result, "superseded", False))
            and request_id >= latest_request_id
        ):
            code = (
                "display_preview"
                if purpose == "preview"
                else "display_effect"
            )
            self._fail(
                code,
                getattr(result, "message", "显示效果应用失败"),
            )
        self.refresh_state()

    @Slot()
    def _on_display_service_state_changed(self) -> None:
        was_hdr_active = self._last_display_hdr_active
        is_hdr_active = bool(
            getattr(self._blue_filter, "hdr_active", False)
        )
        self._last_display_hdr_active = is_hdr_active
        self._effective_policy = self._effects.refresh()
        if not self._in_transaction and hasattr(self, "_state"):
            self.refresh_state()
        if (
            was_hdr_active
            and not is_hdr_active
            and self._runtime_transaction is None
            and bool(self._settings.filter_enabled)
        ):
            self._restore_filter_after_hdr()

    def _restore_filter_after_hdr(self) -> None:
        self._runtime_revision += 1
        desired = self._desired_for_display(self._settings_display_state())
        try:
            result = self._reconcile_effects(
                desired=desired,
                display_revision=self._runtime_revision,
                display_purpose="hdr_restore",
                force_display_commit=True,
            )
        except Exception as exc:
            self._fail("display_hdr_restore", exc)
        else:
            if not result.succeeded:
                self._fail(
                    "display_hdr_restore",
                    self._reconcile_error_message(result),
                )
        finally:
            self._clear_runtime_override()

    def _on_break_tick(self, remaining: int, total: int) -> None:
        if hasattr(self, "_state"):
            self._state = self._build_state()
        self.break_tick.emit(int(remaining), int(total))

    def _on_break_service_state_changed(self) -> None:
        semantic = self._break_semantic_key()
        if semantic == self._break_semantic_snapshot:
            return
        self._break_semantic_snapshot = semantic
        if not self._in_transaction and hasattr(self, "_state"):
            self.refresh_state()

    def _break_semantic_key(self) -> tuple[object, ...]:
        reminder = self._break_reminder
        if reminder is None:
            return ()
        return (
            bool(getattr(reminder, "enabled", False)),
            bool(getattr(reminder, "paused", False)),
            str(getattr(reminder, "phase", "stopped")),
            int(getattr(reminder, "total", 0)),
            str(getattr(reminder, "current_break_kind", "none") or "none"),
            str(getattr(reminder, "prompt_stage", "hidden") or "hidden"),
        )

    def _build_state(self) -> AppState:
        transaction = self._runtime_transaction
        return self._state_projector.build(
            focus_session_ends_at=self._focus_session_ends_at,
            context=self._context_state,
            effective_policy=self._effective_policy,
            update=self._update_state,
            display_override=(
                transaction.proposal
                if transaction is not None and transaction.owns_display
                else None
            ),
            global_pause_override=(
                self._transaction_pause_state(transaction)
                if transaction is not None and transaction.owns_pause
                else None
            ),
        )

    @staticmethod
    def _valid_clock_time(value: str) -> bool:
        try:
            datetime.strptime(value, "%H:%M")
            return True
        except (TypeError, ValueError):
            return False
