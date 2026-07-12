"""Automatic fixed-time or sunrise/sunset display scheduling."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, time, timedelta

from PySide6.QtCore import QObject, QTimer, Signal

from astral import LocationInfo
from astral.sun import sun

log = logging.getLogger(__name__)


class Scheduler(QObject):
    """Schedule blue-light filter state and expose the next boundary.

    ``Scheduler(blue_filter, settings)`` remains supported.  New code should
    call :meth:`set_state_callback` so an ``AppController`` remains the sole
    service writer.
    """

    filter_state_requested = Signal(bool)
    next_event_changed = Signal(object)  # datetime | None
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
        self._blue_filter = blue_filter
        self._settings = settings
        self._now_provider = now_provider or (lambda: datetime.now().astimezone())
        self._sun_calculator = sun_calculator or sun
        self._state_callback: Callable[[bool], None] | None = None

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._on_timer)
        self._next_event: str | None = None
        self._next_event_at: datetime | None = None
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
    def manual_override(self) -> bool:
        return self._manual_override

    def set_state_callback(self, callback: Callable[[bool], None] | None) -> None:
        """Route scheduled state requests through a controller."""
        self._state_callback = callback

    def set_manual_override(self, enabled: bool = True) -> None:
        """Keep a manual choice until the next schedule boundary."""
        value = bool(enabled)
        if self._manual_override == value:
            return
        self._manual_override = value
        self.manual_override_changed.emit(value)

    def start(self) -> None:
        """Apply the current scheduled state immediately and arm one timer."""
        was_running = self._running
        self._running = True
        self.set_manual_override(False)
        self._evaluate_and_schedule(apply_current=True)
        if not was_running:
            self.running_changed.emit(True)
        log.info("Scheduler started")

    def stop(self) -> None:
        self._timer.stop()
        was_running = self._running
        self._running = False
        self.set_manual_override(False)
        self._set_next_event(None, None)
        if was_running:
            self.running_changed.emit(False)
        log.info("Scheduler stopped")

    def reschedule(self) -> None:
        """Recalculate after a location/mode/time change."""
        self._timer.stop()
        self.set_manual_override(False)
        if self._running:
            self._evaluate_and_schedule(apply_current=True)
        else:
            self._evaluate_and_schedule(apply_current=False, arm_timer=False)

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
                should_enable, event, target = self._fixed_schedule(now)
            elif mode == "sun":
                should_enable, event, target = self._sun_schedule(now)
            else:
                raise ValueError(f"Unknown schedule mode: {mode}")
        except Exception as exc:
            log.exception("Failed to calculate display schedule")
            self._set_next_event(None, None)
            self.error.emit("schedule_calculation", str(exc))
            if self._running and arm_timer:
                self._timer.start(60 * 60 * 1000)
            return

        self._set_next_event(event, target)
        if apply_current and not self._manual_override:
            self._request_filter_state(should_enable)
        if self._running and arm_timer:
            delay_ms = max(1000, int((target - now).total_seconds() * 1000))
            self._timer.start(min(delay_ms, 2_147_483_647))
            log.info("Next schedule event: %s at %s", event, target.isoformat())

    def _sun_schedule(self, now: datetime) -> tuple[bool, str, datetime]:
        if self._settings is None:
            raise RuntimeError("Scheduler settings are missing")
        if hasattr(self._settings, "location_configured") and not (
            self._settings.location_configured
        ):
            raise ValueError("Location must be configured for sunrise/sunset mode")

        location = LocationInfo(
            latitude=float(self._settings.latitude),
            longitude=float(self._settings.longitude),
        )
        today = self._sun_calculator(
            location.observer, date=now.date(), tzinfo=now.tzinfo
        )
        sunrise = today["sunrise"]
        sunset = today["sunset"]
        if now < sunrise:
            return True, "sunrise", sunrise
        if now < sunset:
            return False, "sunset", sunset

        tomorrow = self._sun_calculator(
            location.observer,
            date=now.date() + timedelta(days=1),
            tzinfo=now.tzinfo,
        )
        return True, "sunrise", tomorrow["sunrise"]

    def _fixed_schedule(self, now: datetime) -> tuple[bool, str, datetime]:
        if self._settings is None:
            raise RuntimeError("Scheduler settings are missing")
        on_time = self._parse_clock_time(self._settings.schedule_on_time)
        off_time = self._parse_clock_time(self._settings.schedule_off_time)
        days = set(self._settings.schedule_days)
        if not days:
            raise ValueError("At least one schedule day is required")

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
                return True, "off", end

        future_starts = [start for start, _ in intervals if start > now]
        if not future_starts:
            raise RuntimeError("Could not find the next fixed schedule event")
        return False, "on", min(future_starts)

    @staticmethod
    def _parse_clock_time(value: str) -> time:
        try:
            parsed = datetime.strptime(value, "%H:%M")
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid time '{value}', expected HH:MM") from exc
        return parsed.time()

    @staticmethod
    def _normalise_now(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.astimezone()
        return value

    def _request_filter_state(self, enabled: bool) -> None:
        self.filter_state_requested.emit(enabled)
        if self._state_callback is not None:
            self._state_callback(enabled)
            return
        # v0.1.1 compatibility path.  Controller-based startup replaces this
        # with a callback and therefore keeps all writes in one place.
        if self._blue_filter is None:
            return
        if enabled:
            self._blue_filter.enable(self._settings.color_temperature)
        else:
            self._blue_filter.disable()
        if self._settings is not None:
            self._settings.filter_enabled = enabled

    def _set_next_event(
        self, event: str | None, target: datetime | None
    ) -> None:
        changed = event != self._next_event or target != self._next_event_at
        self._next_event = event
        self._next_event_at = target
        if changed:
            self.next_event_changed.emit(target)
