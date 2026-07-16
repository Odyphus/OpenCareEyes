"""Tests for failure-safe, on-demand native metrics."""

import sys
from datetime import datetime, timezone

import pytest
from PySide6.QtCore import QCoreApplication

from opencareyes.application.system_metrics import (
    NativeMetrics,
    SystemMetricsService,
    WindowsSystemMetricsSampler,
)


@pytest.fixture(scope="module")
def qapp():
    return QCoreApplication.instance() or QCoreApplication(sys.argv)


def test_service_does_not_sample_until_explicit_start(qapp):
    calls = []

    def sampler():
        calls.append(1)
        return NativeMetrics(12.5, 50.0, 4096, 8192)

    service = SystemMetricsService(sampler=sampler)
    assert calls == []
    assert service.active is False

    snapshot = service.start()
    assert snapshot.available is True
    assert snapshot.cpu_percent == 12.5
    assert calls == [1]
    assert service.active is True
    service.stop()
    assert service.active is False


def test_sampler_failure_returns_fixed_safe_placeholder(qapp):
    def broken():
        raise OSError("private backend detail C:\\Users\\secret")

    service = SystemMetricsService(sampler=broken)
    snapshot = service.sample_now()

    assert snapshot.available is False
    assert snapshot.cpu_percent is None
    assert snapshot.memory_percent is None
    assert snapshot.message == "系统指标暂时不可用。"
    assert "secret" not in snapshot.message


class FakeKernel32:
    def __init__(self):
        self.times = iter([(100, 300, 200), (150, 400, 300)])

    def GetSystemTimes(self, idle_ptr, kernel_ptr, user_ptr):
        idle, kernel, user = next(self.times)
        idle_ptr._obj.low = idle
        kernel_ptr._obj.low = kernel
        user_ptr._obj.low = user
        return 1

    def GlobalMemoryStatusEx(self, memory_ptr):
        memory_ptr._obj.ullTotalPhys = 1000 * 1024 * 1024
        memory_ptr._obj.ullAvailPhys = 250 * 1024 * 1024
        return 1


def test_native_sampler_calculates_cpu_delta_and_physical_memory():
    sampler = WindowsSystemMetricsSampler(kernel32=FakeKernel32())
    first = sampler()
    second = sampler()

    assert first.cpu_percent is None
    assert second.cpu_percent == 75.0
    assert second.memory_percent == 75.0
    assert second.memory_used_mb == 750
    assert second.memory_total_mb == 1000


def test_snapshot_uses_injected_clock(qapp):
    instant = datetime(2026, 7, 15, tzinfo=timezone.utc)
    service = SystemMetricsService(
        sampler=lambda: NativeMetrics(None, 25.0, 2, 8), now=lambda: instant
    )
    assert service.sample_now().captured_at == instant
