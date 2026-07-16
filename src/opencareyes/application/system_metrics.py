'''Failure-safe, on-demand native system metrics sampling.'''

from __future__ import annotations

import ctypes
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Protocol

from PySide6.QtCore import QObject, QTimer, Signal


@dataclass(frozen=True, slots=True)
class NativeMetrics:
    cpu_percent: float | None
    memory_percent: float
    memory_used_mb: int
    memory_total_mb: int


@dataclass(frozen=True, slots=True)
class SystemMetricsSnapshot:
    cpu_percent: float | None
    memory_percent: float | None
    memory_used_mb: int | None
    memory_total_mb: int | None
    captured_at: datetime
    available: bool
    message: str = ''


class MetricsSampler(Protocol):
    def __call__(self) -> NativeMetrics: ...


class _FILETIME(ctypes.Structure):
    _fields_ = [('low', ctypes.c_uint32), ('high', ctypes.c_uint32)]


class _MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ('dwLength', ctypes.c_uint32),
        ('dwMemoryLoad', ctypes.c_uint32),
        ('ullTotalPhys', ctypes.c_uint64),
        ('ullAvailPhys', ctypes.c_uint64),
        ('ullTotalPageFile', ctypes.c_uint64),
        ('ullAvailPageFile', ctypes.c_uint64),
        ('ullTotalVirtual', ctypes.c_uint64),
        ('ullAvailVirtual', ctypes.c_uint64),
        ('ullAvailExtendedVirtual', ctypes.c_uint64),
    ]


class WindowsSystemMetricsSampler:
    '''Read CPU and physical memory without adding a psutil dependency.'''

    def __init__(self, kernel32: object | None = None) -> None:
        if kernel32 is None:
            if os.name != 'nt':
                raise OSError('Windows metrics are unavailable')
            kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        self._kernel32 = kernel32
        self._previous_times: tuple[int, int, int] | None = None

    def __call__(self) -> NativeMetrics:
        idle = _FILETIME()
        kernel = _FILETIME()
        user = _FILETIME()
        if not self._kernel32.GetSystemTimes(
            ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)
        ):
            raise OSError('GetSystemTimes failed')

        current = tuple(_filetime_to_int(item) for item in (idle, kernel, user))
        cpu_percent: float | None = None
        if self._previous_times is not None:
            idle_delta = current[0] - self._previous_times[0]
            total_delta = (current[1] - self._previous_times[1]) + (
                current[2] - self._previous_times[2]
            )
            if total_delta > 0:
                cpu_percent = 100.0 * (1.0 - max(0, idle_delta) / total_delta)
                cpu_percent = round(min(100.0, max(0.0, cpu_percent)), 1)
        self._previous_times = current

        memory = _MEMORYSTATUSEX()
        memory.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
        if not self._kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)):
            raise OSError('GlobalMemoryStatusEx failed')
        used = max(0, memory.ullTotalPhys - memory.ullAvailPhys)
        total_mb = round(memory.ullTotalPhys / (1024 * 1024))
        used_mb = round(used / (1024 * 1024))
        memory_percent = (
            round(100.0 * used / memory.ullTotalPhys, 1) if memory.ullTotalPhys else 0.0
        )
        return NativeMetrics(cpu_percent, memory_percent, used_mb, total_mb)


def _filetime_to_int(value: _FILETIME) -> int:
    return (int(value.high) << 32) | int(value.low)


class _UnavailableSampler:
    def __call__(self) -> NativeMetrics:
        raise OSError('native metrics unavailable')


class SystemMetricsService(QObject):
    '''Sample only while a consumer explicitly keeps the panel open.'''

    updated = Signal(object)

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        sampler: MetricsSampler | None = None,
        now: Callable[[], datetime] | None = None,
        interval_ms: int = 2_000,
    ) -> None:
        super().__init__(parent)
        if interval_ms < 500:
            raise ValueError('metrics interval must be at least 500ms')
        if sampler is None:
            try:
                sampler = WindowsSystemMetricsSampler()
            except OSError:
                sampler = _UnavailableSampler()
        self._sampler = sampler
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self.sample_now)
        self._last_snapshot: SystemMetricsSnapshot | None = None

    @property
    def active(self) -> bool:
        return self._timer.isActive()

    @property
    def last_snapshot(self) -> SystemMetricsSnapshot | None:
        return self._last_snapshot

    def start(self) -> SystemMetricsSnapshot:
        snapshot = self.sample_now()
        self._timer.start()
        return snapshot

    def stop(self) -> None:
        self._timer.stop()

    def sample_now(self) -> SystemMetricsSnapshot:
        captured_at = self._now()
        try:
            values = self._sampler()
            snapshot = SystemMetricsSnapshot(
                cpu_percent=values.cpu_percent,
                memory_percent=values.memory_percent,
                memory_used_mb=values.memory_used_mb,
                memory_total_mb=values.memory_total_mb,
                captured_at=captured_at,
                available=True,
            )
        except Exception:
            snapshot = SystemMetricsSnapshot(
                cpu_percent=None,
                memory_percent=None,
                memory_used_mb=None,
                memory_total_mb=None,
                captured_at=captured_at,
                available=False,
                message='系统指标暂时不可用。',
            )
        self._last_snapshot = snapshot
        self.updated.emit(snapshot)
        return snapshot
