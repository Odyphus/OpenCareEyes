'''Tests for the explicit-only companion weather service.'''

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone

import pytest
from PySide6.QtCore import QCoreApplication, QObject, Signal
from PySide6.QtNetwork import QNetworkReply

from opencareyes.application.weather_service import (
    REQUEST_TIMEOUT_MS,
    WeatherService,
    condition_from_wmo,
    parse_weather_payload,
)


@pytest.fixture(scope='module')
def qapp():
    app = QCoreApplication.instance() or QCoreApplication(sys.argv)
    return app


class FakeReply(QObject):
    finished = Signal()

    def __init__(self, payload=None, *, error=QNetworkReply.NetworkError.NoError):
        super().__init__()
        self.payload = payload or {}
        self.network_error = error
        self.deleted = False
        self.aborted = False

    def error(self):
        return self.network_error

    def readAll(self):
        return json.dumps(self.payload).encode('utf-8')

    def deleteLater(self):
        self.deleted = True

    def abort(self):
        self.aborted = True


class FakeNetworkManager:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests = []

    def get(self, request):
        self.requests.append(request)
        return self.replies.pop(0)


@pytest.mark.parametrize(
    ('code', 'is_day', 'expected'),
    [
        (0, True, 'clear'),
        (0, False, 'night'),
        (2, True, 'cloudy'),
        (45, True, 'fog'),
        (61, True, 'rain'),
        (85, True, 'snow'),
        (96, True, 'thunder'),
        (123, True, 'unknown'),
    ],
)
def test_wmo_codes_map_to_semantic_conditions(code, is_day, expected):
    assert condition_from_wmo(code, is_day=is_day) == expected


def test_parse_payload_keeps_only_weather_facts():
    fetched_at = datetime(2026, 7, 15, tzinfo=timezone.utc)
    snapshot = parse_weather_payload(
        {
            'latitude': 36.65,
            'longitude': 117.12,
            'current': {
                'time': '2026-07-15T14:00',
                'temperature_2m': 27.5,
                'weather_code': 80,
                'is_day': 1,
            },
        },
        fetched_at=fetched_at,
    )

    assert snapshot.condition == 'rain'
    assert snapshot.temperature_c == 27.5
    assert snapshot.fetched_at == fetched_at
    assert not hasattr(snapshot, 'latitude')
    assert not hasattr(snapshot, 'request_url')


def test_service_never_requests_until_explicit_consent(qapp):
    manager = FakeNetworkManager()
    service = WeatherService(network_manager=manager)
    failures = []
    service.failed.connect(lambda code, message: failures.append((code, message)))

    assert manager.requests == []
    assert service.refresh(36.65, 117.12, consent=False) is False
    assert manager.requests == []
    assert failures == [('consent_required', '请先同意联网获取天气。')]


def test_request_uses_fixed_host_five_second_timeout_and_bounded_fields(qapp):
    reply = FakeReply(
        {
            'current': {
                'time': '2026-07-15T14:00',
                'temperature_2m': 20,
                'weather_code': 71,
                'is_day': 1,
            }
        }
    )
    manager = FakeNetworkManager(reply)
    service = WeatherService(network_manager=manager)
    updates = []
    service.updated.connect(updates.append)

    assert service.refresh(36.65, 117.12, consent=True) is True
    request = manager.requests[0]
    assert request.url().scheme() == 'https'
    assert request.url().host() == 'api.open-meteo.com'
    assert request.url().path() == '/v1/forecast'
    assert request.transferTimeout() == REQUEST_TIMEOUT_MS

    reply.finished.emit()
    assert updates[-1].condition == 'snow'
    assert updates[-1].stale is False
    assert reply.deleted is True


def test_cache_throttles_requests_and_failure_uses_only_two_hour_stale_data(qapp):
    now = [datetime(2026, 7, 15, tzinfo=timezone.utc)]
    good = FakeReply(
        {'current': {'temperature_2m': 20, 'weather_code': 0, 'is_day': 1}}
    )
    bad_one_hour = FakeReply(error=QNetworkReply.NetworkError.TimeoutError)
    bad_three_hours = FakeReply(error=QNetworkReply.NetworkError.TimeoutError)
    manager = FakeNetworkManager(good, bad_one_hour, bad_three_hours)
    service = WeatherService(network_manager=manager, now=lambda: now[0])
    updates = []
    failures = []
    service.updated.connect(updates.append)
    service.failed.connect(lambda code, message: failures.append((code, message)))

    service.refresh(36.65, 117.12, consent=True)
    good.finished.emit()
    now[0] += timedelta(minutes=10)
    assert service.refresh(36.65, 117.12, consent=True) is False
    assert len(manager.requests) == 1

    now[0] += timedelta(minutes=50)
    assert service.refresh(36.65, 117.12, consent=True, force=True) is True
    bad_one_hour.finished.emit()
    assert updates[-1].stale is True

    count = len(updates)
    now[0] += timedelta(hours=2, minutes=1)
    service.refresh(36.65, 117.12, consent=True, force=True)
    bad_three_hours.finished.emit()
    assert len(updates) == count
    assert all('api.open-meteo.com' not in message for _, message in failures)
    assert all('36.65' not in message for _, message in failures)


def test_enabled_weather_refreshes_periodically_and_cancel_stops_timer(qapp):
    first = FakeReply(
        {'current': {'temperature_2m': 20, 'weather_code': 0, 'is_day': 1}}
    )
    second = FakeReply(
        {'current': {'temperature_2m': 18, 'weather_code': 61, 'is_day': 1}}
    )
    manager = FakeNetworkManager(first, second)
    service = WeatherService(network_manager=manager)

    assert service.refresh(36.65, 117.12, consent=True) is True
    assert service._refresh_timer.isActive()
    first.finished.emit()
    service._refresh_periodically()
    assert len(manager.requests) == 2
    service.cancel()
    assert not service._refresh_timer.isActive()
    assert service._location is None
    assert second.aborted is True


def test_cache_is_never_reused_for_a_different_location(qapp):
    now = [datetime(2026, 7, 15, tzinfo=timezone.utc)]
    jinan = FakeReply(
        {'current': {'temperature_2m': 30, 'weather_code': 0, 'is_day': 1}}
    )
    qingdao = FakeReply(
        {'current': {'temperature_2m': 20, 'weather_code': 61, 'is_day': 1}}
    )
    manager = FakeNetworkManager(jinan, qingdao)
    service = WeatherService(network_manager=manager, now=lambda: now[0])
    updates = []
    service.updated.connect(updates.append)

    assert service.refresh(36.65, 117.12, consent=True) is True
    jinan.finished.emit()
    now[0] += timedelta(minutes=5)
    assert service.refresh(36.07, 120.38, consent=True) is True
    assert len(manager.requests) == 2
    qingdao.finished.emit()

    assert [snapshot.condition for snapshot in updates] == ['clear', 'rain']


def test_location_change_aborts_in_flight_request_and_ignores_old_reply(qapp):
    old_reply = FakeReply(
        {'current': {'temperature_2m': 30, 'weather_code': 0, 'is_day': 1}}
    )
    new_reply = FakeReply(
        {'current': {'temperature_2m': 20, 'weather_code': 71, 'is_day': 1}}
    )
    manager = FakeNetworkManager(old_reply, new_reply)
    service = WeatherService(network_manager=manager)
    updates = []
    service.updated.connect(updates.append)

    assert service.refresh(36.65, 117.12, consent=True) is True
    assert service.refresh(36.07, 120.38, consent=True) is True
    assert old_reply.aborted is True
    old_reply.finished.emit()
    assert updates == []
    new_reply.finished.emit()

    assert [snapshot.condition for snapshot in updates] == ['snow']


def test_failure_at_new_location_does_not_emit_stale_data_from_old_location(qapp):
    now = [datetime(2026, 7, 15, tzinfo=timezone.utc)]
    old_reply = FakeReply(
        {'current': {'temperature_2m': 30, 'weather_code': 0, 'is_day': 1}}
    )
    new_reply = FakeReply(error=QNetworkReply.NetworkError.TimeoutError)
    manager = FakeNetworkManager(old_reply, new_reply)
    service = WeatherService(network_manager=manager, now=lambda: now[0])
    updates = []
    service.updated.connect(updates.append)

    service.refresh(36.65, 117.12, consent=True)
    old_reply.finished.emit()
    now[0] += timedelta(minutes=10)
    service.refresh(36.07, 120.38, consent=True)
    new_reply.finished.emit()

    assert len(updates) == 1
    assert updates[0].condition == 'clear'


@pytest.mark.parametrize(
    'payload',
    [b'not-json', {}, {'current': {}}, {'current': {'weather_code': 'bad'}}],
)
def test_invalid_payload_fails_closed(payload):
    with pytest.raises(ValueError):
        parse_weather_payload(payload)
