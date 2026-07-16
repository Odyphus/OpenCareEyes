'''Tests for the single monotonic user utility timer.'''

import sys

import pytest
from PySide6.QtCore import QCoreApplication

from opencareyes.application.utility_timer import UtilityTimerService


@pytest.fixture(scope='module')
def qapp():
    return QCoreApplication.instance() or QCoreApplication(sys.argv)


def test_timer_uses_monotonic_deadline_and_finishes_once(qapp):
    clock = [100.0]
    service = UtilityTimerService(clock=lambda: clock[0])
    ticks = []
    finished = []
    service.tick.connect(ticks.append)
    service.finished.connect(finished.append)

    service.start(5, label='泡杯茶')
    clock[0] += 2.1
    assert service.poll().remaining_seconds == 3
    clock[0] += 2.9
    assert service.poll().status == 'finished'
    service.poll()

    assert ticks == [5, 3, 0]
    assert len(finished) == 1


def test_start_replaces_the_only_existing_timer(qapp):
    clock = [10.0]
    service = UtilityTimerService(clock=lambda: clock[0])
    service.start(30, label='old')
    state = service.start(3, label='new')

    assert state.duration_seconds == 3
    assert state.label == 'new'


def test_pause_freezes_remaining_time(qapp):
    clock = [10.0]
    service = UtilityTimerService(clock=lambda: clock[0])
    service.start(10)
    clock[0] += 3.2
    assert service.pause() is True
    paused = service.state.remaining_seconds
    clock[0] += 100
    assert service.poll().remaining_seconds == paused
    assert service.resume() is True
    clock[0] += paused
    assert service.poll().status == 'finished'


def test_pause_at_deadline_finishes_instead_of_sticking_at_zero(qapp):
    clock = [10.0]
    service = UtilityTimerService(clock=lambda: clock[0])
    finished = []
    service.finished.connect(finished.append)
    service.start(5)

    clock[0] = 15.0
    assert service.pause() is False

    assert service.state.status == 'finished'
    assert service.state.remaining_seconds == 0
    assert len(finished) == 1


def test_non_string_label_is_rejected_without_replacing_running_timer(qapp):
    service = UtilityTimerService()
    original = service.start(30, label='keep')

    with pytest.raises(TypeError):
        service.start(10, label=['private'])

    assert service.state == original


@pytest.mark.parametrize('duration', [0, -1, 86401])
def test_invalid_duration_is_rejected(qapp, duration):
    with pytest.raises(ValueError):
        UtilityTimerService().start(duration)
