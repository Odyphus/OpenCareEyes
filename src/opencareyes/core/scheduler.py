"""Automatic fixed-time or sunrise/sunset display scheduling."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, time, timedelta

from PySide6.QtCore import QObject, QTimer, Signal

from astral import LocationInfo
from astral.sun import sun

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _ScheduleDecision:
    night_active: bool
    current_profile: str
    next_event: str
    next_event_at: datetime
    next_profile: str


@dataclass(frozen=True, slots=True)
class SchedulerRuntimeSnapshot:
    """Rollback state for one controller-owned automation transaction."""

    running: bool
    manual_override: bool
    current_profile: str | None
    next_event: str | None
    next_event_at: datetime | None
    next_profile: str | None
    timer_active: bool
    timer_remaining_ms: int


class Scheduler(QObject):
    """Schedule blue-light filter state and expose the next boundary.

    The legacy first positional argument remains accepted for source
    compatibility, but the scheduler never writes a display service. Runtime
    effects are requested through callbacks/signals so ``AppController`` and
    ``EffectCoordinator`` remain the sole command/effect path.
    """

    filter_state_requested = Signal(bool)
    profile_requested = Signal(str)
    next_event_changed = Signal(object)  # datetime | None
    next_profile_changed = Signal(object)  # str | None
    running_changed = Signal(bool)
    manual_override_changed = Signal(bool)
    error = Signal(str, str)

    def __init__(
        self,
        blue_filter=None,
        settings=None,
        parent: QObject | None = None,
        *,
        now_provider: Callable[[], datetime] | None = None,
        sun_calculator: Callable | None = None,
    ):
        super().__init__(parent)
        _ = blue_filter  # accepted only for source compatibility
        self._settings = settings
        self._now_provider = now_provider or (lambda: datetime.now().astimezone())
        self._sun_calculator = sun_calculator or sun
        self._state_callback: Callable[[bool], None] | None = None
        self._profile_callback: Callable[[str], None] | None = None

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._on_timer)
        self._next_event: str | None = None
        self._next_event_at: datetime | None = None
        self._current_profile: str | None = None
        self._next_profile: str | None = None
        self._running = False
        self._manual_override = False

    @property
    def running(self) -> bool:
        return self._running

    @property
    def next_event(self) -> str | None:
        return self._next_event

    @property
    def next_event_at(self) -> datetime | None:
        return self._next_event_at

    @property
    def current_profile(self) -> str | None:
        return self._current_profile

    @property
    def next_profile(self) -> str | None:
        return self._next_profile

    @property
    def manual_override(self) -> bool:
        return self._manual_override

    def set_state_callback(self, callback: Callable[[bool], None] | None) -> None:
        """Route scheduled state requests through a controller."""
        self._state_callback = callback

    def set_profile_callback(self, callback: Callable[[str], None] | None) -> None:
        """Route selected day/night profiles through a controller."""
        self._profile_callback = callback

    def set_manual_override(self, enabled: bool = True) -> None:
        """Keep a manual choice until the next schedule boundary."""
        value = bool(enabled)
        if self._manual_override == value:
            return
        self._manual_override = value
        self.manual_override_changed.emit(value)

    def start(self, *, defer_apply: bool = False) -> None:
        """Apply the current scheduled state immediately and arm one timer."""
        was_running = self._running
        self._running = True
        self.set_manual_override(False)
        self._evaluate_and_schedule(apply_current=not defer_apply)
        if not was_running:
            self.running_changed.emit(True)
        log.info("Scheduler started")

    def stop(self) -> None:
        self._timer.stop()
        was_running = self._running
        self._running = False
        self.set_manual_override(False)
        self._current_profile = None
        self._set_next_event(None, None, None)
        if was_running:
            self.running_changed.emit(False)
        log.info("Scheduler stopped")

    def reschedule(self, *, defer_apply: bool = False) -> None:
        """Recalculate after a location/mode/time change."""
        self._timer.stop()
        self.set_manual_override(False)
        if self._running:
            self._evaluate_and_schedule(apply_current=not defer_apply)
        else:
            self._evaluate_and_schedule(apply_current=False, arm_timer=False)

    def snapshot_runtime(self) -> SchedulerRuntimeSnapshot:
        """Capture lifecycle and next-action state without applying a profile."""

        remaining = self._timer.remainingTime() if self._timer.isActive() else -1
        return SchedulerRuntimeSnapshot(
            running=self._running,
            manual_override=self._manual_override,
            current_profile=self._current_profile,
            next_event=self._next_event,
            next_event_at=self._next_event_at,
            next_profile=self._next_profile,
            timer_active=self._timer.isActive(),
            timer_remaining_ms=max(1, int(remaining)) if remaining >= 0 else -1,
        )

    def restore_runtime(self, snapshot: SchedulerRuntimeSnapshot) -> None:
        """Restore a snapshot without recalculation or display callbacks."""

        if not isinstance(snapshot, SchedulerRuntimeSnapshot):
            raise TypeError("snapshot must be a SchedulerRuntimeSnapshot")
        old_running = self._running
        old_override = self._manual_override
        self._timer.stop()
        self._running = bool(snapshot.running)
        self._manual_override = bool(snapshot.manual_override)
        self._current_profile = snapshot.current_profile
        self._set_next_event(
            snapshot.next_event,
            snapshot.next_event_at,
            snapshot.next_profile,
        )
        if snapshot.timer_active and snapshot.running:
            self._timer.start(max(1, int(snapshot.timer_remaining_ms)))
        if old_override != self._manual_override:
            self.manual_override_changed.emit(self._manual_override)
        if old_running != self._running:
            self.running_changed.emit(self._running)

    def _on_timer(self) -> None:
        if not self._running:
            return
        self.set_manual_override(False)
        self._evaluate_and_schedule(apply_current=True)

    def _evaluate_and_schedule(
        self,
        *,
        apply_current: bool,
        arm_timer: bool = True,
    ) -> None:
        try:
            now = self._normalise_now(self._now_provider())
            mode = getattr(self._settings, "schedule_mode", "sun")
            if mode == "fixed":
                decision = self._fixed_schedule(now)
            elif mode == "sun":
                decision = self._sun_schedule(now)
            else:
                raise ValueError(f"未知自动化模式：{mode}")
        except Exception:
            log.exception("Failed to calculate display schedule")
            self._current_profile = None
            self._set_next_event(None, None, None)
            self.error.emit(
                "schedule_calculation",
                "无法计算自动化计划，请检查时间、位置和执行日设置。",
            )
            if self._running and arm_timer:
                self._timer.start(60 * 60 * 1000)
            return

        self._current_profile = decision.current_profile
        self._set_next_event(
            decision.next_event,
            decision.next_event_at,
            decision.next_profile,
        )
        if apply_current and not self._manual_override:
            self._request_scheduled_profile(
                decision.night_active, decision.current_profile
            )
        if self._running and arm_timer:
            delay_ms = max(
                1000,
                int((decision.next_event_at - now).total_seconds() * 1000),
            )
            self._timer.start(min(delay_ms, 2_147_483_647))
            log.info(
                "Next schedule event: %s -> %s at %s",
                decision.next_event,
                decision.next_profile,
                decision.next_event_at.isoformat(),
            )

    def _sun_schedule(self, now: datetime) -> _ScheduleDecision:
        if self._settings is None:
            raise RuntimeError("自动化设置不可用")
        if hasattr(self._settings, "location_configured") and not (
            self._settings.location_configured
        ):
            raise ValueError("使用日出日落模式前需要先设置位置")

        # Older integrations did not expose schedule_days in sun mode because
        # v3 treated it as all-week.  Keep that compatibility fallback.
        days = set(getattr(self._settings, "schedule_days", range(7)))
        if not days:
            raise ValueError("请至少选择一个执行日")
        day_profile, night_profile = self._profiles()
        sunrise_offset = self._offset("sunrise_offset")
        sunset_offset = self._offset("sunset_offset")

        location = LocationInfo(
            latitude=float(self._settings.latitude),
            longitude=float(self._settings.longitude),
        )
        calculated: dict[object, dict[str, datetime]] = {}

        def boundaries(day):
            if day not in calculated:
                calculated[day] = self._sun_calculator(
                    location.observer,
                    date=day,
                    tzinfo=now.tzinfo,
                )
            return calculated[day]

        intervals: list[tuple[datetime, datetime]] = []
        for offset in range(-8, 15):
            day = now.date() + timedelta(days=offset)
            if day.weekday() not in days:
                continue
            sunset = boundaries(day)["sunset"] + timedelta(
                minutes=sunset_offset
            )
            next_day = day + timedelta(days=1)
            sunrise = boundaries(next_day)["sunrise"] + timedelta(
                minutes=sunrise_offset
            )
            if sunrise <= sunset:
                raise ValueError("计算得到的日出时间必须晚于前一日的日落时间")
            intervals.append((sunset, sunrise))

        for sunset, sunrise in intervals:
            if sunset <= now < sunrise:
                return _ScheduleDecision(
                    True,
                    night_profile,
                    "sunrise",
                    sunrise,
                    day_profile,
                )

        future_sunsets = [sunset for sunset, _ in intervals if sunset > now]
        if not future_sunsets:
            raise RuntimeError("无法计算下一次日落自动化动作")
        return _ScheduleDecision(
            False,
            day_profile,
            "sunset",
            min(future_sunsets),
            night_profile,
        )

    def _fixed_schedule(self, now: datetime) -> _ScheduleDecision:
        if self._settings is None:
            raise RuntimeError("自动化设置不可用")
        on_time = self._parse_clock_time(self._settings.schedule_on_time)
        off_time = self._parse_clock_time(self._settings.schedule_off_time)
        days = set(self._settings.schedule_days)
        if not days:
            raise ValueError("请至少选择一个执行日")
        day_profile, night_profile = self._profiles()

        intervals: list[tuple[datetime, datetime]] = []
        for offset in range(-8, 9):
            day = now.date() + timedelta(days=offset)
            if day.weekday() not in days:
                continue
            start = datetime.combine(day, on_time, tzinfo=now.tzinfo)
            end_day = day + timedelta(days=1) if off_time <= on_time else day
            end = datetime.combine(end_day, off_time, tzinfo=now.tzinfo)
            intervals.append((start, end))

        for start, end in intervals:
            if start <= now < end:
                return _ScheduleDecision(
                    True,
                    night_profile,
                    "off",
                    end,
                    day_profile,
                )

        future_starts = [start for start, _ in intervals if start > now]
        if not future_starts:
            raise RuntimeError("无法计算下一次固定时间自动化动作")
        return _ScheduleDecision(
            False,
            day_profile,
            "on",
            min(future_starts),
            night_profile,
        )

    def _profiles(self) -> tuple[str, str]:
        day_profile = str(
            getattr(self._settings, "schedule_day_profile", "office")
        )
        night_profile = str(
            getattr(self._settings, "schedule_night_profile", "night")
        )
        if not day_profile or not night_profile:
            raise ValueError("必须选择日间方案和夜间方案")
        return day_profile, night_profile

    def _offset(self, name: str) -> int:
        value = int(getattr(self._settings, name, 0))
        if not -120 <= value <= 120:
            raise ValueError("日出和日落偏移必须在 -120 到 120 分钟之间")
        return value

    @staticmethod
    def _parse_clock_time(value: str) -> time:
        try:
            parsed = datetime.strptime(value, "%H:%M")
        except (TypeError, ValueError) as exc:
            raise ValueError(f"时间格式无效：{value}，应为 HH:MM") from exc
        return parsed.time()

    @staticmethod
    def _normalise_now(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.astimezone()
        return value

    def _request_scheduled_profile(self, night_active: bool, profile: str) -> None:
        self.filter_state_requested.emit(night_active)
        self.profile_requested.emit(profile)
        if self._profile_callback is not None:
            self._profile_callback(profile)
            return
        if self._state_callback is not None:
            self._state_callback(night_active)

    def _set_next_event(
        self,
        event: str | None,
        target: datetime | None,
        next_profile: str | None,
    ) -> None:
        changed = (
            event != self._next_event
            or target != self._next_event_at
            or next_profile != self._next_profile
        )
        profile_changed = next_profile != self._next_profile
        self._next_event = event
        self._next_event_at = target
        self._next_profile = next_profile
        if changed:
            self.next_event_changed.emit(target)
        if profile_changed:
            self.next_profile_changed.emit(next_profile)
