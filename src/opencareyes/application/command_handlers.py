"""Focused command handlers used by the application controller facade."""

from __future__ import annotations

import time
from dataclasses import replace
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Callable

from ..constants import DIM_MAX, DIM_MIN, TEMP_MAX, TEMP_MIN
from ..domain.runtime import DisplayPreview
from ..state import WeatherState

if TYPE_CHECKING:
    from ..controller import AppController


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


class DisplayCommands:
    """Implement display and global-pause commands behind ``AppController``."""

    def __init__(self, controller: AppController):
        self._controller = controller

    def set_filter_enabled(self, enabled: bool) -> bool:
        controller = self._controller
        proposal = replace(
            controller._current_display_state(),
            filter_enabled=bool(enabled),
        )
        return controller._start_display_transaction(
            "filter_toggle",
            proposal,
            mark_manual_override=True,
        )

    def set_dimmer_enabled(self, enabled: bool) -> bool:
        controller = self._controller
        proposal = replace(
            controller._current_display_state(),
            dimmer_enabled=bool(enabled),
        )
        return controller._start_display_transaction(
            "dimmer_toggle",
            proposal,
        )

    def set_color_temperature(
        self,
        kelvin: int,
        persist: bool = True,
    ) -> bool:
        controller = self._controller
        kelvin = max(TEMP_MIN, min(TEMP_MAX, int(kelvin)))
        try:
            controller._require_service(
                controller._blue_filter,
                "blue-light filter",
            )
        except Exception as exc:
            controller._fail("filter_temperature", exc)
            return False
        proposal = replace(
            controller._current_display_state(),
            color_temperature=kelvin,
            preset="custom",
        )
        if not persist:
            return controller._preview_display(
                "filter_temperature",
                DisplayPreview(color_temperature=kelvin),
            )
        return controller._start_display_transaction(
            "filter_temperature",
            proposal,
        )

    def set_dim_level(self, level: int, persist: bool = True) -> bool:
        controller = self._controller
        level = max(DIM_MIN, min(DIM_MAX, int(level)))
        try:
            controller._require_service(controller._dimmer, "screen dimmer")
        except Exception as exc:
            controller._fail("dimmer_level", exc)
            return False
        proposal = replace(
            controller._current_display_state(),
            dim_level=level,
            preset="custom",
        )
        if not persist:
            return controller._preview_display(
                "dimmer_level",
                DisplayPreview(dim_level=level),
            )
        return controller._start_display_transaction(
            "dimmer_level",
            proposal,
        )

    def apply_display_profile(
        self,
        name: str,
        *,
        mark_manual_override: bool = True,
    ) -> bool:
        controller = self._controller
        try:
            proposal = controller._display_profile_state(name)
        except (KeyError, ImportError, SyntaxError, ValueError) as exc:
            controller._fail("unknown_display_profile", exc)
            return False
        try:
            controller._require_service(
                controller._blue_filter,
                "blue-light filter",
            )
            if proposal.dim_level > 0:
                controller._require_service(controller._dimmer, "screen dimmer")
        except Exception as exc:
            controller._fail("display_profile", exc)
            return False
        return controller._start_display_transaction(
            "display_profile",
            proposal,
            mark_manual_override=mark_manual_override,
        )

    def recheck_display_capabilities(self) -> bool:
        """Request a non-blocking display capability refresh."""

        controller = self._controller
        return controller._run(
            "display_recheck",
            lambda: controller._require_and_call(
                controller._blue_filter,
                "refresh_screens",
            ),
            reconcile=False,
            persist_settings=False,
        )

    def restore_display_effects(self) -> bool:
        """Restore the original display and disable related preferences."""

        controller = self._controller
        proposal = replace(
            controller._current_display_state(),
            filter_enabled=False,
            dimmer_enabled=False,
            preset="custom",
        )
        return controller._start_display_transaction(
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
        controller = self._controller
        if minutes is not None and until_next_schedule:
            controller.operation_failed.emit(
                "global_pause",
                "暂停方式只能选择时长或直到下次自动切换。",
            )
            return False
        if minutes is not None and int(minutes) <= 0:
            controller.operation_failed.emit(
                "global_pause",
                "暂停时长必须大于 0 分钟。",
            )
            return False
        if until_next_schedule and (
            controller._scheduler is None or not controller._scheduler.running
        ):
            controller.operation_failed.emit(
                "global_pause",
                "自动化未运行，无法暂停到下次自动切换。",
            )
            return False

        mode = (
            "next_schedule"
            if until_next_schedule
            else ("timed" if minutes is not None else "manual")
        )
        until_timestamp: float | None = None
        if minutes is not None:
            until_timestamp = time.time() + int(minutes) * 60

        return controller._start_pause_transaction(
            "global_pause",
            mode,
            until_timestamp,
        )

    def resume_all(self) -> bool:
        return self._controller._start_pause_transaction(
            "global_resume",
            "none",
            None,
        )


class BreakFocusCommands:
    """Implement break and focus commands behind ``AppController``."""

    def __init__(self, controller: AppController):
        self._controller = controller

    def set_break_enabled(self, enabled: bool) -> bool:
        controller = self._controller
        enabled = bool(enabled)

        def operation() -> None:
            controller._require_service(
                controller._break_reminder,
                "break reminder",
            )
            controller._settings.break_enabled = enabled

        return controller._run("break_toggle", operation)

    def set_focus_enabled(self, enabled: bool) -> bool:
        controller = self._controller
        enabled = bool(enabled)
        transaction = controller._runtime_transaction
        previous_disable_focus = bool(
            transaction is not None and transaction.disable_focus
        )

        def operation() -> None:
            controller._require_service(controller._focus_mode, "focus mode")
            if (
                controller._runtime_transaction is transaction
                and transaction is not None
            ):
                transaction.disable_focus = False
            controller._settings.focus_enabled = enabled
            if not enabled:
                controller._focus_timer.stop()
                controller._focus_session_ends_at = None

        return controller._run(
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

    def set_focus_dim_level(self, level: int) -> bool:
        controller = self._controller
        level = max(0, min(255, int(level)))

        def operation() -> None:
            controller._require_service(controller._focus_mode, "focus mode")
            controller._settings.focus_dim_level = level

        return controller._run("focus_dim_level", operation)

    def set_break_mode(self, mode: str) -> bool:
        controller = self._controller

        def operation() -> None:
            controller._require_service(
                controller._break_reminder,
                "break reminder",
            )
            controller._break_reminder.set_mode(mode)
            controller._settings.break_mode = mode
            if hasattr(controller._settings, "cadence_mode"):
                controller._settings.cadence_mode = mode
            controller._settings.work_duration = (
                controller._break_reminder.work_duration
            )
            controller._settings.break_duration = (
                controller._break_reminder.break_duration
            )
            controller._persist_break_configuration()

        return controller._run("break_mode", operation)

    def set_break_durations(
        self,
        work_seconds: int,
        break_seconds: int,
    ) -> bool:
        controller = self._controller
        return self.set_break_cadence(
            max(1, int(work_seconds)),
            max(1, int(break_seconds)),
            bool(
                getattr(
                    controller._settings,
                    "cadence_long_enabled",
                    False,
                )
            ),
            int(
                getattr(
                    controller._settings,
                    "cadence_long_interval",
                    60 * 60,
                )
            ),
            int(
                getattr(
                    controller._settings,
                    "cadence_long_duration",
                    5 * 60,
                )
            ),
        )

    def set_break_cadence(
        self,
        short_interval: int,
        short_duration: int,
        long_enabled: bool,
        long_interval: int,
        long_duration: int,
    ) -> bool:
        controller = self._controller
        values = (
            max(1, int(short_interval)),
            max(1, int(short_duration)),
            bool(long_enabled),
            max(1, int(long_interval)),
            max(1, int(long_duration)),
        )
        if values[2] and values[3] <= values[0]:
            controller.operation_failed.emit(
                "break_cadence",
                "长休息周期必须大于短休息周期",
            )
            return False

        def operation() -> None:
            controller._require_service(
                controller._break_reminder,
                "break reminder",
            )
            configure = getattr(
                controller._break_reminder,
                "configure_cadence",
                None,
            )
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
                controller._break_reminder.set_mode("custom")
                controller._break_reminder.set_work_duration(values[0])
                controller._break_reminder.set_break_duration(values[1])
            controller._settings.break_mode = "custom"
            controller._settings.work_duration = values[0]
            controller._settings.break_duration = values[1]
            if hasattr(controller._settings, "cadence_mode"):
                controller._settings.cadence_mode = "custom"
                controller._settings.cadence_short_interval = values[0]
                controller._settings.cadence_short_duration = values[1]
                controller._settings.cadence_long_enabled = values[2]
                controller._settings.cadence_long_interval = values[3]
                controller._settings.cadence_long_duration = values[4]

        return controller._run("break_cadence", operation)

    def set_break_reminder_style(self, style: str) -> bool:
        controller = self._controller
        if style not in {"progressive", "fullscreen"}:
            controller.operation_failed.emit(
                "break_reminder_style",
                "不支持该休息提醒方式。",
            )
            return False

        def operation() -> None:
            controller._require_and_call(
                controller._break_reminder,
                "set_reminder_style",
                style,
            )
            controller._settings.break_reminder_style = style

        return controller._run("break_reminder_style", operation)

    def start_due_break(self) -> bool:
        controller = self._controller

        def operation() -> None:
            controller._require_service(
                controller._break_reminder,
                "break reminder",
            )
            if not controller._break_reminder.start_due_break():
                raise RuntimeError("当前没有待开始的休息")

        return controller._run(
            "break_start_due",
            operation,
            reconcile=False,
        )

    def start_break_now(self, kind: str = "short") -> bool:
        """Begin an immediate rest through the authoritative break service."""

        controller = self._controller

        def operation() -> None:
            controller._require_service(
                controller._break_reminder,
                "break reminder",
            )
            if not controller._break_reminder.start_break_now(str(kind)):
                raise RuntimeError("当前无法开始休息")

        return controller._run(
            "break_start_now",
            operation,
            reconcile=False,
        )

    def set_force_break(self, enabled: bool) -> bool:
        controller = self._controller

        def operation() -> None:
            controller._require_service(
                controller._break_reminder,
                "break reminder",
            )
            controller._break_reminder.force_break = bool(enabled)
            controller._settings.force_break = bool(enabled)

        return controller._run("force_break", operation)

    def set_break_countdown_display(self, mode: str) -> bool:
        controller = self._controller
        if mode not in {"floating", "tray", "hidden"}:
            controller.operation_failed.emit(
                "break_display",
                "不支持该倒计时显示方式。",
            )
            return False
        return controller._run(
            "break_display",
            lambda: setattr(
                controller._settings,
                "break_countdown_display",
                mode,
            ),
        )

    def pause_break(self) -> bool:
        controller = self._controller
        return controller._run(
            "break_pause",
            lambda: controller._require_and_call(
                controller._break_reminder,
                "pause",
            ),
        )

    def resume_break(self) -> bool:
        controller = self._controller
        return controller._run(
            "break_resume",
            lambda: controller._require_and_call(
                controller._break_reminder,
                "resume",
            ),
        )

    def snooze_break(self, minutes: int = 5) -> bool:
        controller = self._controller
        minutes = max(1, int(minutes))

        def operation() -> None:
            controller._require_service(
                controller._break_reminder,
                "break reminder",
            )
            if controller._break_reminder.force_break:
                raise ValueError("严格休息模式下不能稍后提醒")
            controller._break_reminder.snooze(minutes * 60)

        return controller._run("break_snooze", operation)

    def skip_break(self) -> bool:
        controller = self._controller
        return controller._run(
            "break_skip",
            lambda: controller._require_and_call(
                controller._break_reminder,
                "skip_break",
            ),
            reconcile=False,
            persist_settings=False,
        )

    def undo_break_snooze(self) -> bool:
        controller = self._controller

        def operation() -> None:
            controller._require_service(
                controller._break_reminder,
                "break reminder",
            )
            undo = getattr(controller._break_reminder, "undo_snooze", None)
            if not callable(undo) or not undo():
                raise RuntimeError("当前没有可撤销的稍后提醒")

        return controller._run(
            "break_snooze_undo",
            operation,
            reconcile=False,
        )

    def start_focus_session(self, minutes: int) -> bool:
        controller = self._controller
        minutes = int(minutes)
        if minutes <= 0:
            controller.operation_failed.emit(
                "focus_session",
                "专注时长必须大于 0 分钟。",
            )
            return False
        if not controller.set_focus_enabled(True):
            return False
        controller._focus_session_ends_at = datetime.now().astimezone() + timedelta(
            minutes=minutes
        )
        controller._focus_timer.start(min(minutes * 60_000, 2_147_483_647))
        controller.refresh_state()
        return True


class AutomationCommands:
    """Implement automation and context commands behind ``AppController``."""

    def __init__(self, controller: AppController):
        self._controller = controller

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
        controller = self._controller
        enabled = bool(enabled)
        selected_mode = mode or controller._settings.schedule_mode
        if selected_mode not in {"sun", "fixed"}:
            controller.operation_failed.emit(
                "schedule_mode",
                "请选择固定时间或日出日落自动化。",
            )
            return False
        if (latitude is None) != (longitude is None):
            controller.operation_failed.emit(
                "schedule_location",
                "纬度和经度必须同时填写。",
            )
            return False
        if latitude is not None and not (-90 <= float(latitude) <= 90):
            controller.operation_failed.emit(
                "schedule_location",
                "纬度必须在 -90 到 90 之间。",
            )
            return False
        if longitude is not None and not (-180 <= float(longitude) <= 180):
            controller.operation_failed.emit(
                "schedule_location",
                "经度必须在 -180 到 180 之间。",
            )
            return False
        if on_time is not None and not controller._valid_clock_time(on_time):
            controller.operation_failed.emit(
                "schedule_time",
                "开启时间格式无效，请使用 HH:MM。",
            )
            return False
        if off_time is not None and not controller._valid_clock_time(off_time):
            controller.operation_failed.emit(
                "schedule_time",
                "关闭时间格式无效，请使用 HH:MM。",
            )
            return False
        selected_days = None if days is None else tuple(sorted(set(days)))
        if selected_days is not None and (
            not selected_days
            or any(
                not isinstance(day, int) or day < 0 or day > 6
                for day in selected_days
            )
        ):
            controller.operation_failed.emit(
                "schedule_days",
                "请至少选择一个有效执行日。",
            )
            return False
        location_configured = (
            controller._settings.location_configured or latitude is not None
        )
        if enabled and selected_mode == "sun" and not location_configured:
            controller.operation_failed.emit(
                "schedule_location",
                "请先设置自动化位置。",
            )
            return False

        from opencareyes.config.presets import PRESETS

        selected_day_profile = day_profile or getattr(
            controller._settings,
            "schedule_day_profile",
            "office",
        )
        selected_night_profile = night_profile or getattr(
            controller._settings,
            "schedule_night_profile",
            "night",
        )
        if (
            selected_day_profile not in PRESETS
            or selected_night_profile not in PRESETS
        ):
            controller.operation_failed.emit(
                "schedule_profile",
                "请选择有效的日间和夜间显示方案。",
            )
            return False
        for value in (sunrise_offset, sunset_offset):
            if value is not None and not -120 <= int(value) <= 120:
                controller.operation_failed.emit(
                    "schedule_offset",
                    "日出和日落偏移必须在 -120 到 120 分钟之间。",
                )
                return False

        def operation() -> None:
            controller._require_service(controller._scheduler, "scheduler")
            controller._settings.schedule_mode = selected_mode
            if latitude is not None:
                controller._settings.latitude = float(latitude)
                controller._settings.longitude = float(longitude)
                if city is not None:
                    controller._settings.city = str(city).strip()
                controller._settings.location_configured = True
            if on_time is not None:
                controller._settings.schedule_on_time = on_time
            if off_time is not None:
                controller._settings.schedule_off_time = off_time
            if selected_days is not None:
                controller._settings.schedule_days = selected_days
            if hasattr(controller._settings, "schedule_day_profile"):
                controller._settings.schedule_day_profile = selected_day_profile
            if hasattr(controller._settings, "schedule_night_profile"):
                controller._settings.schedule_night_profile = selected_night_profile
            if sunrise_offset is not None and hasattr(
                controller._settings,
                "sunrise_offset",
            ):
                controller._settings.sunrise_offset = int(sunrise_offset)
            if sunset_offset is not None and hasattr(
                controller._settings,
                "sunset_offset",
            ):
                controller._settings.sunset_offset = int(sunset_offset)
            controller._settings.filter_schedule_enabled = enabled
            if enabled:
                controller._scheduler.start(defer_apply=True)
            else:
                controller._scheduler.stop()

        return controller._run_schedule_update(
            "schedule",
            operation,
            apply_current_profile=enabled,
        )

    def set_location(
        self,
        latitude: float,
        longitude: float,
        city: str = "",
    ) -> bool:
        controller = self._controller
        latitude = float(latitude)
        longitude = float(longitude)
        if not (-90 <= latitude <= 90) or not (-180 <= longitude <= 180):
            controller.operation_failed.emit(
                "location",
                "纬度或经度超出有效范围。",
            )
            return False

        def operation() -> None:
            controller._settings.latitude = latitude
            controller._settings.longitude = longitude
            controller._settings.city = city.strip()
            controller._settings.location_configured = True
            if controller._scheduler is not None and controller._scheduler.running:
                controller._scheduler.reschedule(defer_apply=True)

        return controller._run_schedule_update(
            "location",
            operation,
            apply_current_profile=controller._scheduler is not None,
        )

    def set_smart_pause_enabled(self, enabled: bool) -> bool:
        return self._controller._set_context_preference(
            "smart_pause_enabled",
            bool(enabled),
        )

    def set_fullscreen_pause_enabled(self, enabled: bool) -> bool:
        return self._controller._set_context_preference(
            "fullscreen_pause_enabled",
            bool(enabled),
        )

    def set_natural_rest_enabled(self, enabled: bool) -> bool:
        return self._controller._set_context_preference(
            "natural_rest_enabled",
            bool(enabled),
        )

    def upsert_app_rule(self, rule) -> bool:
        controller = self._controller

        def operation() -> None:
            updater = getattr(controller._settings, "upsert_app_rule", None)
            if not callable(updater):
                raise RuntimeError("Application rules are unavailable")
            updater(rule)

        return controller._run("app_rule", operation)

    def remove_app_rule(self, app_id: str) -> bool:
        controller = self._controller

        def operation() -> None:
            remover = getattr(controller._settings, "remove_app_rule", None)
            if not callable(remover):
                raise RuntimeError("Application rules are unavailable")
            remover(app_id)

        return controller._run("app_rule", operation)

    def resume_breaks_for_current_context(self) -> bool:
        controller = self._controller
        if controller._context_runtime is None:
            controller.operation_failed.emit(
                "context_override",
                "智能免打扰当前不可用。",
            )
            return False
        return bool(
            controller._context_runtime.resume_breaks_for_current_context()
        )

    def set_context_preference(self, name: str, value: bool) -> bool:
        controller = self._controller
        return controller._run(
            name,
            lambda: setattr(controller._settings, name, value),
        )

    def on_scheduled_filter_state_requested(self, enabled: bool) -> None:
        controller = self._controller
        controller._clear_next_schedule_pause()
        profile = (
            getattr(controller._settings, "schedule_night_profile", "night")
            if enabled
            else getattr(controller._settings, "schedule_day_profile", "office")
        )
        controller.apply_display_profile(profile, mark_manual_override=False)

    def on_scheduled_profile_requested(self, profile: str) -> None:
        controller = self._controller
        controller._clear_next_schedule_pause()
        controller.apply_display_profile(
            str(profile),
            mark_manual_override=False,
        )

    def clear_next_schedule_pause(self) -> None:
        controller = self._controller
        mode, _until = controller._current_pause_values()
        if controller._is_globally_paused() and mode == "next_schedule":
            controller._start_pause_transaction(
                "global_resume",
                "none",
                None,
            )

    def run_schedule_update(
        self,
        code: str,
        operation: Callable[[], object],
        *,
        apply_current_profile: bool,
    ) -> bool:
        """Stage automation outside QSettings until its display is verified."""

        from opencareyes.controller import _OwnedSettingsSnapshot

        controller = self._controller
        previous = controller._runtime_transaction
        settings_snapshot = (
            previous.settings_snapshot
            if previous is not None and previous.settings_snapshot is not None
            else controller._snapshot_owned_settings(_SCHEDULE_SETTING_KEYS)
        )
        scheduler_snapshot = (
            previous.scheduler_snapshot
            if previous is not None and previous.scheduler_snapshot is not None
            else controller._snapshot_scheduler_runtime()
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
            if previous is not None and previous.scheduler_proposal is not None
            else scheduler_snapshot
        )
        controller._apply_owned_settings_unchecked(settings_base)
        if scheduler_base is not None:
            controller._restore_scheduler_runtime(scheduler_base)

        operation_error: Exception | None = None
        restore_errors: list[str] = []
        settings_proposal = None
        scheduler_proposal = None
        profile = ""
        controller._in_transaction = True
        try:
            operation()
            settings_proposal = controller._snapshot_owned_settings(
                _SCHEDULE_SETTING_KEYS
            )
            scheduler_proposal = controller._snapshot_scheduler_runtime()
            if (
                apply_current_profile
                and controller._scheduler is not None
                and bool(getattr(controller._scheduler, "running", False))
            ):
                profile = str(
                    getattr(controller._scheduler, "current_profile", "") or ""
                )
        except Exception as exc:
            operation_error = exc
        finally:
            try:
                controller._apply_owned_settings_unchecked(settings_snapshot)
            except Exception as exc:
                restore_errors.append(str(exc))
            try:
                if scheduler_snapshot is not None:
                    controller._restore_scheduler_runtime(scheduler_snapshot)
            except Exception as exc:
                restore_errors.append(str(exc))
            controller._in_transaction = False
        if operation_error is not None or restore_errors:
            controller._fail(
                code,
                operation_error or "自动化暂存状态恢复失败",
            )
            if restore_errors:
                controller._fail(
                    f"{code}_rollback",
                    "自动化设置或运行状态回滚不完整："
                    + "; ".join(restore_errors),
                )
            controller.refresh_state(force=True)
            return False
        if not isinstance(settings_proposal, _OwnedSettingsSnapshot):
            controller._fail(code, "无法暂存自动化设置")
            controller.refresh_state(force=True)
            return False

        if not profile:
            if (
                previous is not None
                and previous.settings_proposal is not None
                and previous.owns_display
            ):
                return controller._start_display_transaction(
                    code,
                    previous.baseline,
                    mark_manual_override=False,
                    settings_snapshot=settings_snapshot,
                    scheduler_snapshot=scheduler_snapshot,
                    settings_proposal=settings_proposal,
                    scheduler_proposal=scheduler_proposal,
                )
            controller._in_transaction = True
            try:
                controller._apply_owned_settings_unchecked(settings_proposal)
                if scheduler_proposal is not None:
                    controller._restore_scheduler_runtime(scheduler_proposal)
                controller._sync_settings_checked()
            except Exception as exc:
                rollback_errors = controller._restore_owned_configuration(
                    settings_snapshot,
                    scheduler_snapshot,
                )
                controller._in_transaction = False
                controller._fail(code, exc)
                if rollback_errors:
                    controller._fail(
                        f"{code}_rollback",
                        "自动化设置或运行状态回滚不完整："
                        + "; ".join(rollback_errors),
                    )
                controller.refresh_state(force=True)
                return False
            controller._in_transaction = False
            controller.refresh_state()
            return True
        try:
            proposal = controller._display_profile_state(profile)
            controller._require_service(
                controller._blue_filter,
                "blue-light filter",
            )
            if proposal.dim_level > 0:
                controller._require_service(controller._dimmer, "screen dimmer")
        except Exception as exc:
            rollback_errors = controller._restore_owned_configuration(
                settings_snapshot,
                scheduler_snapshot,
            )
            controller._fail(code, exc)
            if rollback_errors:
                controller._fail(
                    f"{code}_rollback",
                    "自动化设置或运行状态回滚不完整："
                    + "; ".join(rollback_errors),
                )
            controller.refresh_state(force=True)
            return False
        return controller._start_display_transaction(
            code,
            proposal,
            mark_manual_override=False,
            settings_snapshot=settings_snapshot,
            scheduler_snapshot=scheduler_snapshot,
            settings_proposal=settings_proposal,
            scheduler_proposal=scheduler_proposal,
        )


class CompanionToolCommands:
    """Implement companion and quick-tool commands behind ``AppController``."""

    def __init__(self, controller: AppController):
        self._controller = controller

    def set_companion_enabled(self, enabled: bool) -> bool:
        controller = self._controller
        enabled = bool(enabled)
        previous = bool(getattr(controller._settings, "companion_enabled", True))

        def apply_runtime(value: bool) -> None:
            setter = getattr(controller._companion, "set_enabled", None)
            if callable(setter):
                result = setter(value)
                if result is False:
                    raise RuntimeError("Companion visibility could not be changed")

        def operation() -> None:
            controller._settings.companion_enabled = enabled
            apply_runtime(enabled)

        return controller._run(
            "companion_enabled",
            operation,
            reconcile=False,
            rollback=lambda: apply_runtime(previous),
        )

    def set_active_pet(self, pet_id: str) -> bool:
        controller = self._controller
        normalized = str(pet_id).strip().lower()
        previous = str(getattr(controller._settings, "active_pet_id", "snow_ferret"))

        def select(value: str) -> None:
            selector = getattr(controller._companion, "set_active_pet", None)
            if not callable(selector):
                selector = getattr(controller._companion, "select_pet", None)
            if callable(selector):
                result = selector(value)
                if result is False:
                    raise RuntimeError("Pet pack could not be loaded")
            preferences = getattr(controller._settings, "pet_preferences", {})
            selected = preferences.get(value, {}) if isinstance(preferences, dict) else {}
            accessory_setter = getattr(controller._companion, "set_manual_accessory", None)
            if callable(accessory_setter) and isinstance(selected, dict):
                for slot, item_id in selected.items():
                    accessory_setter(str(slot), str(item_id))

        def operation() -> None:
            controller._settings.active_pet_id = normalized
            if hasattr(controller._settings, "recovery_pet_id"):
                controller._settings.recovery_pet_id = ""
            select(normalized)

        return controller._run(
            "active_pet",
            operation,
            reconcile=False,
            rollback=lambda: select(previous),
        )

    def set_pet_scale(self, percent: int) -> bool:
        controller = self._controller
        value = int(percent)
        previous = int(getattr(controller._settings, "pet_scale_percent", 100))

        def apply_runtime(scale: int) -> None:
            setter = getattr(controller._companion, "set_scale", None)
            if callable(setter):
                setter(scale)

        def operation() -> None:
            controller._settings.pet_scale_percent = value
            apply_runtime(value)

        return controller._run(
            "pet_scale",
            operation,
            reconcile=False,
            rollback=lambda: apply_runtime(previous),
        )

    def set_pet_anchor(
        self,
        edge: str,
        offset: int,
        x: int | None = None,
        y: int | None = None,
    ) -> bool:
        controller = self._controller

        def operation() -> None:
            controller._settings.pet_anchor_edge = edge
            controller._settings.pet_anchor_offset = int(offset)
            if edge == "free":
                if x is None or y is None:
                    raise ValueError("Free pet anchors require x and y coordinates")
                controller._settings.pet_x = int(x)
                controller._settings.pet_y = int(y)

        return controller._run("pet_anchor", operation, reconcile=False)

    def set_pet_accessory(self, slot: str, item_id: str | None) -> bool:
        controller = self._controller
        pet_id = str(getattr(controller._settings, "active_pet_id", "snow_ferret"))

        def operation() -> None:
            preferences = dict(getattr(controller._settings, "pet_preferences", {}))
            slots = dict(preferences.get(pet_id, {}))
            if item_id in {None, ""}:
                slots.pop(str(slot), None)
            else:
                slots[str(slot)] = str(item_id)
            preferences[pet_id] = slots
            controller._settings.pet_preferences = preferences
            setter = getattr(controller._companion, "set_manual_accessory", None)
            if not callable(setter):
                setter = getattr(controller._companion, "set_appearance", None)
            if callable(setter):
                setter(str(slot), item_id)

        return controller._run("pet_accessory", operation, reconcile=False)

    def upsert_app_prop_rule(self, app_id: str, prop_id: str) -> bool:
        controller = self._controller
        app = str(app_id).strip().lower()
        prop = str(prop_id).strip().lower()

        def operation() -> None:
            rules = [
                dict(rule)
                for rule in getattr(controller._settings, "app_prop_rules", ())
                if str(rule.get("app_id", "")).lower() != app
            ]
            rules.append({"app_id": app, "prop_id": prop})
            controller._settings.app_prop_rules = rules

        return controller._run("app_prop_rule", operation, reconcile=False)

    def remove_app_prop_rule(self, app_id: str) -> bool:
        controller = self._controller
        app = str(app_id).strip().lower()

        def operation() -> None:
            controller._settings.app_prop_rules = [
                dict(rule)
                for rule in getattr(controller._settings, "app_prop_rules", ())
                if str(rule.get("app_id", "")).lower() != app
            ]

        return controller._run("app_prop_rule", operation, reconcile=False)

    def set_follow_active_monitor(self, enabled: bool) -> bool:
        controller = self._controller
        return controller._run(
            "follow_active_monitor",
            lambda: setattr(controller._settings, "follow_active_monitor", bool(enabled)),
            reconcile=False,
        )

    def set_window_avoidance_enabled(self, enabled: bool) -> bool:
        controller = self._controller
        return controller._run(
            "window_avoidance",
            lambda: setattr(
                controller._settings,
                "window_avoidance_enabled",
                bool(enabled),
            ),
            reconcile=False,
        )

    def set_companion_sound_enabled(self, enabled: bool) -> bool:
        controller = self._controller
        return controller._run(
            "companion_sound",
            lambda: setattr(
                controller._settings,
                "companion_sound_enabled",
                bool(enabled),
            ),
            reconcile=False,
        )

    def set_hourly_chime_enabled(self, enabled: bool) -> bool:
        controller = self._controller
        return controller._run(
            "hourly_chime",
            lambda: setattr(controller._settings, "hourly_chime_enabled", bool(enabled)),
            reconcile=False,
        )

    def set_weather_enabled(
        self,
        enabled: bool,
        consent: bool = False,
    ) -> bool:
        controller = self._controller
        enabled = bool(enabled)
        if enabled and not consent:
            controller.operation_failed.emit(
                "weather_consent",
                "开启天气前需要确认会向 Open-Meteo 发送经纬度和网络 IP。",
            )
            return False
        if enabled and not bool(getattr(controller._settings, "location_configured", False)):
            controller.operation_failed.emit(
                "weather_location",
                "请先在自动日程中选择城市或填写位置。",
            )
            return False
        previous = bool(getattr(controller._settings, "weather_enabled", False))

        def apply_runtime(value: bool) -> None:
            if controller._weather_service is None:
                if value:
                    raise RuntimeError("Weather service is unavailable")
                return
            if value:
                controller._weather_state = WeatherState(status="loading")
                refresh = getattr(controller._weather_service, "refresh", None)
                if callable(refresh):
                    refresh(
                        float(controller._settings.latitude),
                        float(controller._settings.longitude),
                        consent=True,
                        force=True,
                    )
                else:
                    controller._weather_service.start(
                        float(controller._settings.latitude),
                        float(controller._settings.longitude),
                    )
            else:
                cancel = getattr(controller._weather_service, "cancel", None)
                if callable(cancel):
                    cancel()
                else:
                    stop = getattr(controller._weather_service, "stop", None)
                    if callable(stop):
                        stop()
                controller._weather_state = WeatherState(status="disabled")

        def operation() -> None:
            controller._settings.weather_enabled = enabled
            apply_runtime(enabled)

        return controller._run(
            "weather",
            operation,
            reconcile=False,
            rollback=lambda: apply_runtime(previous),
        )

    def show_quick_tool(self, tool_id: str) -> bool:
        controller = self._controller
        tool = str(tool_id).strip().lower()
        if tool not in {"timer", "notes", "system", "wardrobe", "more"}:
            controller.operation_failed.emit("quick_tool", "不支持这个快捷工具。")
            return False
        controller.quick_tool_requested.emit(tool)
        return True

    def set_quick_actions(self, actions) -> bool:
        controller = self._controller
        return controller._run(
            "quick_actions",
            lambda: setattr(controller._settings, "quick_actions", tuple(actions)),
            reconcile=False,
        )

    def offer_pet_item(self, item_id: str) -> bool:
        controller = self._controller
        item = str(item_id).strip().lower()
        if item not in {"yarn_ball", "hot_cocoa", "pine_cone"}:
            controller.operation_failed.emit("pet_item", "不支持这个互动道具。")
            return False
        handler = getattr(controller._companion, "offer_item", None)
        if callable(handler) and handler(item) is False:
            controller.operation_failed.emit("pet_item", "伙伴现在无法接住这个道具。")
            return False
        controller.refresh_companion_presentation(force=True)
        return True

    def select_rest_scene(self, scene_id: str) -> bool:
        controller = self._controller
        return controller._run(
            "rest_scene",
            lambda: setattr(controller._settings, "break_rest_scene", scene_id),
            reconcile=False,
        )
