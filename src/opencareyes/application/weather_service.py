'''Explicit, privacy-conscious Open-Meteo weather service.'''

from __future__ import annotations

import json
import math
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Callable

from PySide6.QtCore import QObject, QTimer, QUrl, QUrlQuery, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest


OPEN_METEO_ENDPOINT = 'https://api.open-meteo.com/v1/forecast'
OPEN_METEO_ATTRIBUTION = 'Weather data by Open-Meteo.com'
OPEN_METEO_ATTRIBUTION_URL = 'https://open-meteo.com/'
REQUEST_TIMEOUT_MS = 5_000
REFRESH_INTERVAL = timedelta(minutes=30)
STALE_LIMIT = timedelta(hours=2)
MAX_RESPONSE_BYTES = 64 * 1024


@dataclass(frozen=True, slots=True)
class WeatherSnapshot:
    '''Weather facts without request URLs or precise location data.'''

    condition: str
    weather_code: int
    temperature_c: float | None
    is_day: bool
    observed_at: datetime | None
    fetched_at: datetime
    stale: bool = False
    attribution: str = OPEN_METEO_ATTRIBUTION
    attribution_url: str = OPEN_METEO_ATTRIBUTION_URL


def condition_from_wmo(weather_code: int, *, is_day: bool = True) -> str:
    '''Map Open-Meteo WMO codes to stable semantic conditions.'''

    if weather_code == 0:
        return 'clear' if is_day else 'night'
    if weather_code in {1, 2, 3}:
        return 'cloudy'
    if weather_code in {45, 48}:
        return 'fog'
    if weather_code in {
        51,
        53,
        55,
        56,
        57,
        61,
        63,
        65,
        66,
        67,
        80,
        81,
        82,
    }:
        return 'rain'
    if weather_code in {71, 73, 75, 77, 85, 86}:
        return 'snow'
    if weather_code in {95, 96, 99}:
        return 'thunder'
    return 'unknown'


def parse_weather_payload(
    payload: bytes | bytearray | dict[str, object],
    *,
    fetched_at: datetime | None = None,
) -> WeatherSnapshot:
    '''Parse the bounded subset of Open-Meteo used by the companion.'''

    if isinstance(payload, (bytes, bytearray)):
        if len(payload) > MAX_RESPONSE_BYTES:
            raise ValueError('weather response is too large')
        try:
            data = json.loads(bytes(payload).decode('utf-8'))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError('invalid weather response') from exc
    else:
        data = payload

    if not isinstance(data, dict):
        raise ValueError('invalid weather response')
    current = data.get('current')
    if not isinstance(current, dict):
        raise ValueError('weather response has no current conditions')

    try:
        weather_code = int(current['weather_code'])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError('weather response has no valid weather code') from exc
    if weather_code < 0 or weather_code > 999:
        raise ValueError('weather response has an invalid weather code')

    raw_is_day = current.get('is_day', 1)
    if raw_is_day not in (0, 1, False, True):
        raise ValueError('weather response has an invalid day flag')
    is_day = bool(raw_is_day)

    temperature_c: float | None = None
    raw_temperature = current.get('temperature_2m')
    if raw_temperature is not None:
        try:
            temperature_c = float(raw_temperature)
        except (TypeError, ValueError) as exc:
            raise ValueError('weather response has an invalid temperature') from exc
        if not math.isfinite(temperature_c):
            raise ValueError('weather response has an invalid temperature')

    fetched = fetched_at or datetime.now(timezone.utc)
    observed_at = _parse_observed_at(current.get('time'), fetched)
    return WeatherSnapshot(
        condition=condition_from_wmo(weather_code, is_day=is_day),
        weather_code=weather_code,
        temperature_c=temperature_c,
        is_day=is_day,
        observed_at=observed_at,
        fetched_at=fetched,
    )


def _parse_observed_at(value: object, fetched_at: datetime) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return None
    if parsed.tzinfo is None and fetched_at.tzinfo is not None:
        parsed = parsed.replace(tzinfo=fetched_at.tzinfo)
    return parsed


class WeatherService(QObject):
    '''Fetch weather only after an explicit, consent-bearing command.'''

    updated = Signal(object)
    failed = Signal(str, str)

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        network_manager: QNetworkAccessManager | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        super().__init__(parent)
        self._network = network_manager or QNetworkAccessManager(self)
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._cached: WeatherSnapshot | None = None
        self._cached_location: tuple[float, float] | None = None
        self._in_flight: QNetworkReply | None = None
        self._in_flight_location: tuple[float, float] | None = None
        self._location: tuple[float, float] | None = None
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(int(REFRESH_INTERVAL.total_seconds() * 1000))
        self._refresh_timer.timeout.connect(self._refresh_periodically)

    @property
    def in_flight(self) -> bool:
        return self._in_flight is not None

    @property
    def last_snapshot(self) -> WeatherSnapshot | None:
        return self._cached

    def refresh(
        self,
        latitude: float,
        longitude: float,
        *,
        consent: bool,
        force: bool = False,
    ) -> bool:
        '''Start one request; construction and background time never call it.'''

        if not consent:
            self.failed.emit('consent_required', '请先同意联网获取天气。')
            return False
        if not _valid_coordinate(latitude, longitude):
            self.failed.emit('invalid_location', '天气位置无效。')
            return False
        location = (float(latitude), float(longitude))
        self._location = location
        if not self._refresh_timer.isActive():
            self._refresh_timer.start()
        if self._in_flight is not None:
            if self._in_flight_location == location:
                return False
            # A changed location invalidates the old request. Keeping it alive
            # can otherwise publish or cache weather for the previous place.
            previous_reply = self._in_flight
            self._in_flight = None
            self._in_flight_location = None
            previous_reply.abort()
            previous_reply.deleteLater()

        now = self._now()
        if (
            not force
            and self._cached is not None
            and self._cached_location == location
        ):
            if now - self._cached.fetched_at < REFRESH_INTERVAL:
                self.updated.emit(replace(self._cached, stale=False))
                return False

        url = QUrl(OPEN_METEO_ENDPOINT)
        query = QUrlQuery()
        query.addQueryItem('latitude', format(float(latitude), '.6f'))
        query.addQueryItem('longitude', format(float(longitude), '.6f'))
        query.addQueryItem('current', 'temperature_2m,weather_code,is_day')
        query.addQueryItem('timezone', 'auto')
        url.setQuery(query)

        request = QNetworkRequest(url)
        request.setTransferTimeout(REQUEST_TIMEOUT_MS)
        request.setRawHeader(b'User-Agent', b'OpenCareEyes-Weather')
        reply = self._network.get(request)
        self._in_flight = reply
        self._in_flight_location = location
        reply.finished.connect(lambda reply=reply: self._finish(reply))
        return True

    def cancel(self) -> None:
        '''Abort an in-flight request when the user disables weather.'''

        self._refresh_timer.stop()
        self._location = None
        reply = self._in_flight
        self._in_flight = None
        self._in_flight_location = None
        if reply is None:
            return
        reply.abort()
        reply.deleteLater()

    def _refresh_periodically(self) -> None:
        if self._location is None:
            return
        latitude, longitude = self._location
        self.refresh(latitude, longitude, consent=True, force=True)

    def _finish(self, reply: QNetworkReply) -> None:
        if reply is not self._in_flight:
            reply.deleteLater()
            return
        request_location = self._in_flight_location
        self._in_flight = None
        self._in_flight_location = None
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                self._emit_failure(
                    'network_error',
                    '暂时无法获取天气。',
                    request_location,
                )
                return
            payload = bytes(reply.readAll())
            snapshot = parse_weather_payload(payload, fetched_at=self._now())
            self._cached = snapshot
            self._cached_location = request_location
            self.updated.emit(snapshot)
        except (TypeError, ValueError):
            self._emit_failure(
                'invalid_response',
                '天气服务返回了无效数据。',
                request_location,
            )
        finally:
            reply.deleteLater()

    def _emit_failure(
        self,
        code: str,
        message: str,
        request_location: tuple[float, float] | None,
    ) -> None:
        now = self._now()
        if (
            self._cached is not None
            and self._cached_location == request_location
            and now - self._cached.fetched_at <= STALE_LIMIT
        ):
            self.updated.emit(replace(self._cached, stale=True))
        self.failed.emit(code, message)


def _valid_coordinate(latitude: object, longitude: object) -> bool:
    try:
        lat = float(latitude)
        lon = float(longitude)
    except (TypeError, ValueError):
        return False
    return math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180
