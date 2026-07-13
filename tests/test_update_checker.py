"""Tests for the non-blocking manual update coordinator."""

from __future__ import annotations

from opencareyes.application.update_checker import UpdateChecker
from opencareyes.state import UpdateState


class FakeService:
    def __init__(self, result: UpdateState):
        self.state = UpdateState("idle", result.current_version)
        self.result = result
        self.calls = 0

    def check_for_updates(self):
        self.calls += 1
        return self.result


class HoldingPool:
    def __init__(self):
        self.task = None

    def start(self, task):
        self.task = task


def test_checker_is_explicit_single_flight_and_non_blocking(qtbot):
    service = FakeService(
        UpdateState(
            "available",
            "0.3.0",
            "0.4.0",
            "https://github.com/Odyphus/OpenCareEyes/releases/tag/v0.4.0",
        )
    )
    pool = HoldingPool()
    checker = UpdateChecker(service, thread_pool=pool)

    assert service.calls == 0
    assert checker.check() is True
    assert checker.state.status == "checking"
    assert checker.check() is False
    assert service.calls == 0

    pool.task.run()
    qtbot.waitUntil(lambda: checker.state.status == "available")

    assert service.calls == 1
    assert checker.state.latest_version == "0.4.0"


def test_checker_publishes_visible_failure(qtbot):
    checker = UpdateChecker(
        FakeService(UpdateState("failed", "0.4.0")),
        thread_pool=HoldingPool(),
    )
    failures = []
    checker.operation_failed.connect(lambda code, message: failures.append((code, message)))

    assert checker.check() is True
    checker._thread_pool.task.run()
    qtbot.waitUntil(lambda: bool(failures))

    assert failures[0][0] == "update_check"
    assert "网络" in failures[0][1]
