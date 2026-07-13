"""Tests for serial, non-blocking Gamma work."""

from __future__ import annotations

from PySide6.QtTest import QSignalSpy

from opencareyes.core.display_worker import QueuedBlueLightFilter


class FakeBackend:
    enabled = False
    current_temperature = 6500
    hdr_active = False
    capability_verified = True
    last_error_code = ""
    last_error_message = ""

    def __init__(self):
        self.calls = []

    def enable(self, temperature):
        self.calls.append(("enable", temperature))
        self.current_temperature = temperature
        self.enabled = True
        return True

    def disable(self):
        self.calls.append(("disable", None))
        self.enabled = False
        return True

    def set_temperature(self, temperature):
        self.calls.append(("temperature", temperature))
        self.current_temperature = temperature
        return True

    def refresh_screens(self):
        self.calls.append(("refresh", None))
        return True


class FailingBackend(FakeBackend):
    def enable(self, temperature):
        raise PermissionError(
            13,
            "private native detail",
            r"C:\Users\Alice\Private\gamma-state.bin",
        )


def test_worker_reports_pending_until_verified_result(qtbot):
    backend = FakeBackend()
    service = QueuedBlueLightFilter(backend)
    try:
        assert service.enable(4200) is True
        assert service.pending is True
        assert service.enabled is False

        qtbot.waitUntil(lambda: not service.pending)

        assert service.enabled is True
        assert backend.calls == [("enable", 4200)]
    finally:
        service.shutdown()


def test_temperature_preview_is_coalesced_to_twenty_hertz(qtbot):
    backend = FakeBackend()
    service = QueuedBlueLightFilter(backend)
    try:
        service.set_temperature(5000)
        service.set_temperature(4500)
        service.set_temperature(4100)
        assert backend.calls == []

        qtbot.waitUntil(lambda: not service.pending)

        assert backend.calls == [("temperature", 4100)]
    finally:
        service.shutdown()


def test_commit_after_preview_has_an_independent_verified_barrier(qtbot):
    backend = FakeBackend()
    service = QueuedBlueLightFilter(backend)
    results = QSignalSpy(service.request_finished)
    try:
        preview = service.preview_temperature(4300, revision=7)
        commit = service.request_temperature(
            4300,
            revision=8,
            purpose="commit",
        )

        assert preview.request_id != commit.request_id
        assert service.preview_pending is False
        assert service.commit_pending is True
        qtbot.waitUntil(lambda: not service.pending)

        assert backend.calls == [("temperature", 4300)]
        assert results.count() == 2
        assert results.at(0)[0].request_id == preview.request_id
        assert results.at(0)[0].superseded is True
        assert results.at(1)[0].request_id == commit.request_id
        assert results.at(1)[0].success is True
    finally:
        service.shutdown()


def test_worker_exception_exposes_only_fixed_localized_message(qtbot):
    service = QueuedBlueLightFilter(FailingBackend())
    failures = QSignalSpy(service.operation_failed)
    results = QSignalSpy(service.request_finished)
    try:
        assert service.enable(4200) is True
        qtbot.waitUntil(lambda: failures.count() == 1)

        assert failures.at(0) == [
            "gamma_worker_exception",
            "色温效果未能安全应用，已保持原始显示。",
        ]
        assert results.at(0)[0].message == failures.at(0)[1]
        assert service.last_error_message == failures.at(0)[1]
        assert "private" not in failures.at(0)[1].casefold()
        assert "C:\\Users" not in failures.at(0)[1]
    finally:
        service.shutdown()
