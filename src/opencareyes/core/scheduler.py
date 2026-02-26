"""Sunrise/sunset scheduler for automatic blue-light filter toggling."""

import logging
from datetime import datetime, timezone, timedelta

from PySide6.QtCore import QObject, QTimer

from astral import LocationInfo
from astral.sun import sun

log = logging.getLogger(__name__)


class Scheduler(QObject):
    """Schedules blue-light filter on/off based on sunrise and sunset."""

    def __init__(self, blue_filter, settings, parent=None):
        super().__init__(parent)
        self._blue_filter = blue_filter
        self._settings = settings
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._on_timer)
        self._next_event: str | None = None  # "sunrise" or "sunset"
        self._running = False

    def start(self):
        """Calculate next sunrise/sunset and start the scheduling timer."""
        self._running = True
        self._schedule_next()
        log.info("Scheduler started")

    def stop(self):
        """Stop the scheduling timer."""
        self._timer.stop()
        self._running = False
        self._next_event = None
        log.info("Scheduler stopped")

    def _on_timer(self):
        """Fired when the scheduled event time arrives."""
        if self._next_event == "sunset":
            self._on_sunset()
        elif self._next_event == "sunrise":
            self._on_sunrise()
        if self._running:
            self._schedule_next()

    def _on_sunset(self):
        """Enable blue light filter at sunset."""
        temp = self._settings.color_temperature
        self._blue_filter.enable(temp)
        log.info("Sunset reached -- blue light filter enabled at %dK", temp)

    def _on_sunrise(self):
        """Disable blue light filter at sunrise."""
        self._blue_filter.disable()
        log.info("Sunrise reached -- blue light filter disabled")

    def _schedule_next(self):
        """Calculate the next sunrise or sunset and arm the timer."""
        lat = self._settings.latitude
        lon = self._settings.longitude
        loc = LocationInfo(latitude=lat, longitude=lon)
        now = datetime.now(timezone.utc)

        try:
            s = sun(loc.observer, date=now.date(), tzinfo=timezone.utc)
        except Exception:
            log.exception("Failed to calculate sun times; retrying tomorrow")
            self._timer.start(60 * 60 * 1000)  # retry in 1 hour
            return

        sunrise_dt = s["sunrise"]
        sunset_dt = s["sunset"]

        # Determine which event is next
        if now < sunrise_dt:
            self._next_event = "sunrise"
            target = sunrise_dt
        elif now < sunset_dt:
            self._next_event = "sunset"
            target = sunset_dt
        else:
            # Both today's events have passed; schedule tomorrow's sunrise
            try:
                tomorrow = now.date() + timedelta(days=1)
                s_tomorrow = sun(loc.observer, date=tomorrow, tzinfo=timezone.utc)
                self._next_event = "sunrise"
                target = s_tomorrow["sunrise"]
            except Exception:
                log.exception("Failed to calculate tomorrow's sun times")
                self._timer.start(60 * 60 * 1000)
                return

        delay_ms = max(1000, int((target - now).total_seconds() * 1000))
        self._timer.start(delay_ms)
        log.info("Next event: %s in %d seconds", self._next_event, delay_ms // 1000)
