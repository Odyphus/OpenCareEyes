"""Tests for offline holiday appearance events."""

from datetime import date

import pytest

from opencareyes.application.holiday_service import HolidayService


def test_christmas_window_is_offline_and_semantic():
    events = HolidayService().events_for(date(2026, 12, 25))
    assert [(event.event_id, event.appearance_key) for event in events] == [
        ("christmas", "holiday.christmas")
    ]


@pytest.mark.parametrize(
    "day",
    [date(2024, 2, 24), date(2026, 3, 3), date(2029, 2, 27), date(2040, 2, 26)],
)
def test_lantern_festival_uses_bundled_date_table(day):
    assert HolidayService().events_for(day)[0].event_id == "lantern_festival"


def test_disabled_pack_returns_no_events():
    assert HolidayService().events_for(date(2026, 12, 25), pack="none") == ()


def test_unknown_pack_is_rejected():
    with pytest.raises(ValueError, match="unsupported"):
        HolidayService().events_for(date(2026, 1, 1), pack="downloaded-pack")
