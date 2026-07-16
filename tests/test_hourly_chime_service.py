'''Tests for the wall-clock hourly companion chime scheduler.'''

import sys
import wave
from datetime import datetime
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication

from opencareyes.application.hourly_chime_service import HourlyChimeService


@pytest.fixture(scope='module')
def qapp():
    return QCoreApplication.instance() or QCoreApplication(sys.argv)


def test_emits_12_hour_number_once_per_wall_clock_hour(qapp):
    now = [datetime(2026, 7, 15, 0, 0, 1)]
    service = HourlyChimeService(now=lambda: now[0])
    service.configure(True, True, '23:00', '07:00')
    emitted = []
    service.chime.connect(lambda hour, sound: emitted.append((hour, sound)))

    assert service.poll() is True
    assert service.poll() is False
    now[0] = datetime(2026, 7, 15, 12, 0, 0)
    assert service.poll() is True
    now[0] = datetime(2026, 7, 15, 13, 0, 0)
    assert service.poll() is True

    assert emitted == [(12, False), (12, True), (1, True)]


@pytest.mark.parametrize(
    ('current', 'sound_allowed'),
    [
        (datetime(2026, 7, 15, 22, 0), True),
        (datetime(2026, 7, 15, 23, 0), False),
        (datetime(2026, 7, 16, 0, 0), False),
        (datetime(2026, 7, 16, 6, 0), False),
        (datetime(2026, 7, 16, 7, 0), True),
    ],
)
def test_quiet_hours_cross_midnight(qapp, current, sound_allowed):
    service = HourlyChimeService(now=lambda: current)
    service.configure(True, True, '23:00', '07:00')
    emitted = []
    service.chime.connect(lambda hour, sound: emitted.append((hour, sound)))

    assert service.poll() is True
    assert emitted == [(current.hour % 12 or 12, sound_allowed)]


def test_sound_preference_does_not_suppress_number_animation(qapp):
    service = HourlyChimeService(now=lambda: datetime(2026, 7, 15, 9, 0))
    service.configure(True, False, '23:00', '07:00')
    emitted = []
    service.chime.connect(lambda hour, sound: emitted.append((hour, sound)))

    assert service.poll() is True
    assert emitted == [(9, False)]


def test_runtime_and_injected_context_gates_suppress_entire_chime(qapp):
    now = [datetime(2026, 7, 15, 9, 0)]
    context_allowed = [False]
    service = HourlyChimeService(
        now=lambda: now[0],
        allowed=lambda: context_allowed[0],
    )
    service.configure(True, True, '23:00', '07:00')
    emitted = []
    service.chime.connect(lambda hour, sound: emitted.append((hour, sound)))

    assert service.poll() is False
    context_allowed[0] = True
    assert service.poll() is False
    now[0] = datetime(2026, 7, 15, 10, 0)
    service.set_allowed(False)
    assert service.poll() is False
    now[0] = datetime(2026, 7, 15, 11, 0)
    service.set_allowed(True)
    assert service.poll() is True
    assert emitted == [(11, True)]


def test_sensor_failure_fails_closed(qapp):
    def broken_sensor():
        raise RuntimeError('unavailable')

    service = HourlyChimeService(
        now=lambda: datetime(2026, 7, 15, 9, 0),
        allowed=broken_sensor,
    )
    service.configure(True, True, '23:00', '07:00')
    emitted = []
    service.chime.connect(lambda hour, sound: emitted.append((hour, sound)))

    assert service.poll() is False
    assert emitted == []


def test_non_boundary_and_disabled_service_do_not_emit(qapp):
    now = [datetime(2026, 7, 15, 9, 1)]
    service = HourlyChimeService(now=lambda: now[0])
    service.configure(True, True, '23:00', '07:00')
    emitted = []
    service.chime.connect(lambda hour, sound: emitted.append((hour, sound)))

    assert service.poll() is False
    now[0] = datetime(2026, 7, 15, 10, 0)
    service.configure(False, True, '23:00', '07:00')
    assert service.poll() is False
    assert emitted == []


@pytest.mark.parametrize('value', ['7:00', '24:00', '23:60', '', object()])
def test_quiet_time_validation(qapp, value):
    service = HourlyChimeService()
    error = TypeError if not isinstance(value, str) else ValueError
    with pytest.raises(error):
        service.configure(True, True, value, '07:00')


def test_default_is_stopped_and_configure_does_not_start(qapp):
    service = HourlyChimeService()
    service.configure(True, True, '23:00', '07:00')
    assert service.running is False


def test_invalid_configuration_does_not_partially_change_live_preferences(qapp):
    service = HourlyChimeService(now=lambda: datetime(2026, 7, 15, 9, 0))
    service.configure(False, False, '23:00', '07:00')
    emitted = []
    service.chime.connect(lambda hour, sound: emitted.append((hour, sound)))

    with pytest.raises(ValueError):
        service.configure(True, True, '08:00', 'invalid')

    assert service.poll() is False
    assert emitted == []


def test_bundled_chime_is_a_short_mono_pcm_wave(qapp):
    asset = (
        Path(__file__).resolve().parents[1]
        / 'assets'
        / 'pets'
        / 'snow_ferret'
        / 'sounds'
        / 'chime.wav'
    )
    with wave.open(str(asset), 'rb') as wav:
        assert wav.getnchannels() == 1
        assert wav.getsampwidth() == 2
        assert wav.getframerate() == 44_100
        assert 0.5 < wav.getnframes() / wav.getframerate() < 0.8
