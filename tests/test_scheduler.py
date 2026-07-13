"""Tests for immediate and reschedulable display automation."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import sys

import pytest
from PySide6.QtCore import QCoreApplication
from opencareyes.core.scheduler import Scheduler


@pytest.fixture(scope="module")
def qapp():
    return QCoreApplication.instance() or QCoreApplication(sys.argv)


class FakeFilter:
    def __init__(self):
        self.enabled = False
        self.calls = []

    def enable(self, temperature):
        self.enabled = True
        self.calls.append(("enable", temperature))

    def disable(self):
        self.enabled = False
        self.calls.append(("disable",))


def fixed_settings():
    return SimpleNamespace(
        schedule_mode="fixed",
        schedule_on_time="19:00",
        schedule_off_time="07:00",
        schedule_days=(0, 1, 2, 3, 4, 5, 6),
        color_temperature=4200,
        filter_enabled=False,
    )


def test_fixed_schedule_requests_current_night_state_immediately(qapp):
    now = datetime(2026, 7, 12, 20, 0, tzinfo=timezone.utc)
    display = FakeFilter()
    settings = fixed_settings()
    scheduler = Scheduler(display, settings, now_provider=lambda: now)
    requested = []
    scheduler.set_state_callback(requested.append)

    scheduler.start()

    assert requested == [True]
    assert display.calls == []
    assert settings.filter_enabled is False
    assert scheduler.running is True
    assert scheduler.next_event == "off"
    assert scheduler.current_profile == "night"
    assert scheduler.next_profile == "office"
    assert scheduler.next_event_at == datetime(
        2026, 7, 13, 7, 0, tzinfo=timezone.utc
    )
    scheduler.stop()


def test_fixed_schedule_reschedule_recomputes_and_applies(qapp):
    current = [datetime(2026, 7, 12, 12, 0, tzinfo=timezone.utc)]
    display = FakeFilter()
    settings = fixed_settings()
    scheduler = Scheduler(display, settings, now_provider=lambda: current[0])
    requested = []
    scheduler.set_state_callback(requested.append)

    scheduler.start()
    assert requested == [False]
    assert display.calls == []
    assert scheduler.next_event == "on"
    assert scheduler.current_profile == "office"
    assert scheduler.next_profile == "night"

    settings.schedule_on_time = "13:00"
    scheduler.reschedule()
    assert scheduler.next_event_at.hour == 13
    assert requested == [False, False]
    assert display.calls == []
    scheduler.stop()


def test_sun_schedule_exposes_next_event_and_uses_controller_callback(qapp):
    now = datetime(2026, 7, 12, 22, 0, tzinfo=timezone.utc)
    settings = SimpleNamespace(
        schedule_mode="sun",
        location_configured=True,
        latitude=31.2,
        longitude=121.5,
        color_temperature=4500,
        filter_enabled=False,
    )

    def fake_sun(_observer, *, date, tzinfo):
        return {
            "sunrise": datetime.combine(
                date, datetime.min.time(), tzinfo=tzinfo
            )
            + timedelta(hours=6),
            "sunset": datetime.combine(
                date, datetime.min.time(), tzinfo=tzinfo
            )
            + timedelta(hours=18),
        }

    requested = []
    scheduler = Scheduler(
        None,
        settings,
        now_provider=lambda: now,
        sun_calculator=fake_sun,
    )
    scheduler.set_state_callback(requested.append)
    scheduler.start()

    assert requested == [True]
    assert scheduler.next_event == "sunrise"
    assert scheduler.current_profile == "night"
    assert scheduler.next_profile == "office"
    assert scheduler.next_event_at.date() == (now + timedelta(days=1)).date()
    scheduler.stop()


def test_manual_override_is_cleared_at_boundary(qapp):
    current = [datetime(2026, 7, 12, 20, 0, tzinfo=timezone.utc)]
    settings = fixed_settings()
    requested = []
    scheduler = Scheduler(None, settings, now_provider=lambda: current[0])
    scheduler.set_state_callback(requested.append)
    scheduler.start()
    scheduler.set_manual_override(True)

    current[0] = datetime(2026, 7, 13, 7, 1, tzinfo=timezone.utc)
    scheduler._on_timer()

    assert scheduler.manual_override is False
    assert requested == [True, False]
    assert scheduler.next_event == "on"
    scheduler.stop()


def test_unexpected_schedule_failure_exposes_only_a_localized_message(qapp):
    def fail_in_english():
        raise RuntimeError("private calculation detail")

    scheduler = Scheduler(
        None,
        fixed_settings(),
        now_provider=fail_in_english,
    )
    failures = []
    scheduler.error.connect(
        lambda code, message: failures.append((code, message))
    )

    scheduler.start()

    assert failures == [
        (
            "schedule_calculation",
            "无法计算自动化计划，请检查时间、位置和执行日设置。",
        )
    ]
    scheduler.stop()


def test_fixed_schedule_requests_configured_profile(qapp):
    now = datetime(2026, 7, 13, 20, 0, tzinfo=timezone.utc)
    settings = fixed_settings()
    settings.schedule_day_profile = "reading"
    settings.schedule_night_profile = "movie"
    requested = []
    scheduler = Scheduler(None, settings, now_provider=lambda: now)
    scheduler.set_profile_callback(requested.append)

    scheduler.start()

    assert requested == ["movie"]
    assert scheduler.current_profile == "movie"
    assert scheduler.next_profile == "reading"
    scheduler.stop()


def test_sun_schedule_respects_days_and_offsets(qapp):
    current = [datetime(2026, 7, 12, 22, 0, tzinfo=timezone.utc)]
    settings = SimpleNamespace(
        schedule_mode="sun",
        schedule_days=(0,),  # Monday sunset starts the only weekly interval.
        schedule_day_profile="reading",
        schedule_night_profile="night",
        sunrise_offset=-15,
        sunset_offset=30,
        location_configured=True,
        latitude=31.2,
        longitude=121.5,
    )

    def fake_sun(_observer, *, date, tzinfo):
        return {
            "sunrise": datetime.combine(
                date, datetime.min.time(), tzinfo=tzinfo
            )
            + timedelta(hours=6),
            "sunset": datetime.combine(
                date, datetime.min.time(), tzinfo=tzinfo
            )
            + timedelta(hours=18),
        }

    requested = []
    scheduler = Scheduler(
        None,
        settings,
        now_provider=lambda: current[0],
        sun_calculator=fake_sun,
    )
    scheduler.set_profile_callback(requested.append)
    scheduler.start()

    assert requested == ["reading"]
    assert scheduler.next_event == "sunset"
    assert scheduler.next_event_at == datetime(
        2026, 7, 13, 18, 30, tzinfo=timezone.utc
    )

    current[0] = datetime(2026, 7, 13, 20, 0, tzinfo=timezone.utc)
    scheduler._on_timer()
    assert requested[-1] == "night"
    assert scheduler.next_event == "sunrise"
    assert scheduler.next_event_at == datetime(
        2026, 7, 14, 5, 45, tzinfo=timezone.utc
    )
    scheduler.stop()
