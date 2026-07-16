"""Privacy-safe foreground-window and monitor geometry sampling."""

from __future__ import annotations

import ctypes
import math
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Protocol

from PySide6.QtGui import QGuiApplication

if sys.platform == "win32":
    from opencareyes.platform import win32_api as api
else:  # pragma: no cover - Windows is the supported production platform.
    api = None

__all__ = [
    "MonitorGeometry",
    "QtLogicalWindowGeometryBackend",
    "ScreenRect",
    "Win32WindowGeometryBackend",
    "WindowGeometryBackend",
    "WindowGeometrySnapshot",
]


@dataclass(frozen=True, slots=True)
class ScreenRect:
    """A rectangle in one coordinate space, with exclusive right/bottom edges."""

    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return max(0, self.right - self.left)

    @property
    def height(self) -> int:
        return max(0, self.bottom - self.top)

    @property
    def is_valid(self) -> bool:
        return self.width > 0 and self.height > 0

    def intersects(self, other: ScreenRect) -> bool:
        return (
            self.left < other.right
            and self.right > other.left
            and self.top < other.bottom
            and self.bottom > other.top
        )

    def intersection_area(self, other: ScreenRect) -> int:
        width = max(0, min(self.right, other.right) - max(self.left, other.left))
        height = max(0, min(self.bottom, other.bottom) - max(self.top, other.top))
        return width * height

    def contains_point(self, x: int, y: int) -> bool:
        return self.left <= x < self.right and self.top <= y < self.bottom


@dataclass(frozen=True, slots=True)
class MonitorGeometry:
    monitor_id: str
    work_area: ScreenRect
    device_name: str | None = None


@dataclass(frozen=True, slots=True)
class WindowGeometrySnapshot:
    """Geometry only: deliberately excludes titles, process paths and app IDs."""

    foreground_hwnd: int = 0
    foreground_rect: ScreenRect | None = None
    foreground_rects: tuple[ScreenRect, ...] = ()
    active_monitor_id: str | None = None
    monitors: tuple[MonitorGeometry, ...] = ()
    geometry_available: bool = True


class WindowGeometryBackend(Protocol):
    def sample(self) -> WindowGeometrySnapshot: ...


class Win32WindowGeometryBackend:
    """Sample the foreground HWND and geometry without identifying its owner."""

    def __init__(
        self,
        *,
        ignored_hwnds: Callable[[], set[int] | frozenset[int]] | None = None,
    ) -> None:
        self._ignored_hwnds = ignored_hwnds or (lambda: frozenset())

    def sample(self) -> WindowGeometrySnapshot:
        if api is None:
            return WindowGeometrySnapshot(geometry_available=False)

        monitors = self._monitors()
        if not monitors:
            return WindowGeometrySnapshot(geometry_available=False)
        hwnd = _handle_value(api.GetForegroundWindow())
        if not hwnd:
            return WindowGeometrySnapshot(monitors=monitors)

        if hwnd in self._ignored_hwnds():
            return WindowGeometrySnapshot(
                monitors=monitors,
                geometry_available=False,
            )

        monitor = api.MonitorFromWindow(
            api.wintypes.HWND(hwnd),
            api.MONITOR_DEFAULTTONEAREST,
        )
        active_monitor_id = _monitor_id(monitor) if monitor else None
        if api.IsIconic(api.wintypes.HWND(hwnd)):
            return WindowGeometrySnapshot(monitors=monitors)
        foreground_rect = self._window_rect(hwnd)
        if foreground_rect is None:
            return WindowGeometrySnapshot(
                foreground_hwnd=hwnd,
                active_monitor_id=active_monitor_id,
                monitors=monitors,
                geometry_available=False,
            )
        return WindowGeometrySnapshot(
            foreground_hwnd=hwnd,
            foreground_rect=foreground_rect,
            foreground_rects=(foreground_rect,),
            active_monitor_id=active_monitor_id,
            monitors=monitors,
        )

    @staticmethod
    def _window_rect(hwnd: int) -> ScreenRect | None:
        rect = api.RECT()
        result = api.DwmGetWindowAttribute(
            api.wintypes.HWND(hwnd),
            api.DWMWA_EXTENDED_FRAME_BOUNDS,
            ctypes.byref(rect),
            ctypes.sizeof(rect),
        )
        if result != 0:
            if not api.GetWindowRect(api.wintypes.HWND(hwnd), ctypes.byref(rect)):
                return None
        sampled = _screen_rect(rect)
        return sampled if sampled.is_valid else None

    @staticmethod
    def _monitors() -> tuple[MonitorGeometry, ...]:
        monitors: list[MonitorGeometry] = []

        @api.MONITORENUMPROC
        def collect(monitor, _hdc, _rect, _data):
            info = api.MONITORINFOEXW()
            info.cbSize = ctypes.sizeof(api.MONITORINFOEXW)
            if api.GetMonitorInfoW(monitor, ctypes.byref(info)):
                work_area = _screen_rect(info.rcWork)
                if work_area.is_valid:
                    monitors.append(
                        MonitorGeometry(
                            monitor_id=_monitor_id(monitor),
                            work_area=work_area,
                            device_name=str(info.szDevice).strip() or None,
                        )
                    )
            return True

        if not api.EnumDisplayMonitors(None, None, collect, 0):
            return ()
        return tuple(monitors)


class QtLogicalWindowGeometryBackend:
    """Map native physical geometry into Qt's logical desktop coordinates."""

    def __init__(
        self,
        backend: WindowGeometryBackend,
        *,
        screens: Callable[[], Iterable[object]] | None = None,
    ) -> None:
        self._backend = backend
        self._screens = screens or _application_screens

    def sample(self) -> WindowGeometrySnapshot:
        native = self._backend.sample()
        if not native.geometry_available:
            return WindowGeometrySnapshot(
                foreground_hwnd=native.foreground_hwnd,
                geometry_available=False,
            )
        screen_geometries = _qt_screen_geometries(self._screens)
        mappings: dict[str, tuple[MonitorGeometry, MonitorGeometry]] = {}
        logical_monitors: list[MonitorGeometry] = []
        for monitor in native.monitors:
            name = _normalise_device_name(monitor.device_name)
            logical_work_area = screen_geometries.get(name)
            if logical_work_area is None:
                continue
            logical = MonitorGeometry(
                monitor_id=monitor.monitor_id,
                work_area=logical_work_area,
                device_name=monitor.device_name,
            )
            mappings[monitor.monitor_id] = (monitor, logical)
            logical_monitors.append(logical)

        mapping_complete = bool(native.monitors) and len(mappings) == len(
            native.monitors
        )
        active_mapped = (
            native.active_monitor_id is None
            or native.active_monitor_id in mappings
        )
        if not mapping_complete or not active_mapped:
            return WindowGeometrySnapshot(
                foreground_hwnd=native.foreground_hwnd,
                geometry_available=False,
            )

        active_monitor_id = (
            native.active_monitor_id
            if native.active_monitor_id in mappings
            else None
        )
        logical_foregrounds = _map_foreground_parts(
            native.foreground_rect,
            mappings,
        )
        if native.foreground_rect is not None and not logical_foregrounds:
            return WindowGeometrySnapshot(
                foreground_hwnd=native.foreground_hwnd,
                geometry_available=False,
            )
        logical_foreground = _bounding_rect(logical_foregrounds)
        return WindowGeometrySnapshot(
            foreground_hwnd=native.foreground_hwnd,
            foreground_rect=logical_foreground,
            foreground_rects=logical_foregrounds,
            active_monitor_id=active_monitor_id,
            monitors=tuple(logical_monitors),
        )


def _application_screens() -> tuple[object, ...]:
    application = QGuiApplication.instance()
    return tuple(application.screens()) if application is not None else ()


def _qt_screen_geometries(
    screens: Callable[[], Iterable[object]],
) -> dict[str, ScreenRect]:
    try:
        available_screens = tuple(screens())
    except (RuntimeError, TypeError):
        return {}
    candidates: dict[str, list[ScreenRect]] = {}
    for screen in available_screens:
        try:
            name = _normalise_device_name(screen.name())
            geometry = screen.availableGeometry()
            work_area = ScreenRect(
                int(geometry.x()),
                int(geometry.y()),
                int(geometry.x() + geometry.width()),
                int(geometry.y() + geometry.height()),
            )
        except (AttributeError, RuntimeError, TypeError, ValueError):
            continue
        if name and work_area.is_valid:
            candidates.setdefault(name, []).append(work_area)
    return {
        name: geometries[0]
        for name, geometries in candidates.items()
        if len(geometries) == 1
    }


def _map_foreground_parts(
    foreground: ScreenRect | None,
    mappings: dict[str, tuple[MonitorGeometry, MonitorGeometry]],
) -> tuple[ScreenRect, ...]:
    if foreground is None:
        return ()
    mapped_parts: list[ScreenRect] = []
    for native, logical in mappings.values():
        clipped = _intersection(foreground, native.work_area)
        if clipped is None:
            continue
        mapped_parts.append(
            _map_rect(clipped, native.work_area, logical.work_area)
        )
    return tuple(mapped_parts)


def _bounding_rect(parts: tuple[ScreenRect, ...]) -> ScreenRect | None:
    if not parts:
        return None
    return ScreenRect(
        min(part.left for part in parts),
        min(part.top for part in parts),
        max(part.right for part in parts),
        max(part.bottom for part in parts),
    )


def _map_rect(rect: ScreenRect, source: ScreenRect, target: ScreenRect) -> ScreenRect:
    scale_x = target.width / source.width
    scale_y = target.height / source.height
    return ScreenRect(
        math.floor(target.left + (rect.left - source.left) * scale_x),
        math.floor(target.top + (rect.top - source.top) * scale_y),
        math.ceil(target.left + (rect.right - source.left) * scale_x),
        math.ceil(target.top + (rect.bottom - source.top) * scale_y),
    )


def _intersection(first: ScreenRect, second: ScreenRect) -> ScreenRect | None:
    intersection = ScreenRect(
        max(first.left, second.left),
        max(first.top, second.top),
        min(first.right, second.right),
        min(first.bottom, second.bottom),
    )
    return intersection if intersection.is_valid else None


def _normalise_device_name(value: object) -> str:
    separator = chr(92)
    name = str(value or '').strip().replace('/', separator).casefold()
    prefix = f'{separator}{separator}.{separator}'
    return name[len(prefix) :] if name.startswith(prefix) else name


def _screen_rect(rect) -> ScreenRect:
    return ScreenRect(
        left=int(rect.left),
        top=int(rect.top),
        right=int(rect.right),
        bottom=int(rect.bottom),
    )


def _handle_value(handle) -> int:
    return int(getattr(handle, "value", handle) or 0)


def _monitor_id(handle) -> str:
    return f"monitor-{_handle_value(handle):x}"
