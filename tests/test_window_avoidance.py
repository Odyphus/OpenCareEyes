from dataclasses import fields
from types import SimpleNamespace

from PySide6.QtCore import QRect

from opencareyes.application.window_avoidance import (
    MovementRequest,
    WindowAvoidanceService,
)
from opencareyes.platform.window_geometry import (
    MonitorGeometry,
    QtLogicalWindowGeometryBackend,
    ScreenRect,
    Win32WindowGeometryBackend,
    WindowGeometrySnapshot,
)
import opencareyes.platform.window_geometry as geometry_module


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class FakeBackend:
    def __init__(self, snapshot: WindowGeometrySnapshot) -> None:
        self.snapshot = snapshot
        self.samples = 0

    def sample(self) -> WindowGeometrySnapshot:
        self.samples += 1
        return self.snapshot


class FakeScreen:
    def __init__(self, name: str, available_geometry: QRect) -> None:
        self._name = name
        self._available_geometry = available_geometry

    def name(self) -> str:
        return self._name

    def availableGeometry(self) -> QRect:  # noqa: N802
        return self._available_geometry


def _monitor(
    monitor_id: str,
    left: int,
    top: int,
    right: int,
    bottom: int,
) -> MonitorGeometry:
    return MonitorGeometry(monitor_id, ScreenRect(left, top, right, bottom))


def _settle(service: WindowAvoidanceService, clock: FakeClock):
    assert service.poll() is None
    clock.advance(1)
    assert service.poll() is None
    clock.advance(1)
    return service.poll()


def test_intersection_moves_to_nearest_clear_corner_after_two_seconds():
    clock = FakeClock()
    monitor = _monitor("main", 0, 0, 1000, 800)
    pet = ScreenRect(700, 600, 800, 700)
    backend = FakeBackend(
        WindowGeometrySnapshot(
            foreground_hwnd=41,
            foreground_rect=ScreenRect(650, 550, 900, 800),
            active_monitor_id="main",
            monitors=(monitor,),
        )
    )
    service = WindowAvoidanceService(backend, lambda: pet, lambda: True, clock=clock)
    emitted = []
    service.move_requested.connect(emitted.append)

    request = _settle(service, clock)

    assert request == MovementRequest((884, 16), "window_avoidance")
    assert emitted == [request]
    assert backend.samples == 3
    assert service.poll() is None


def test_active_monitor_migration_supports_negative_coordinates_and_multiple_screens():
    clock = FakeClock()
    left = _monitor("left", -1280, 0, 0, 1024)
    right = _monitor("right", 0, 0, 1920, 1080)
    pet = ScreenRect(1700, 900, 1800, 1000)
    backend = FakeBackend(
        WindowGeometrySnapshot(
            foreground_hwnd=55,
            foreground_rect=ScreenRect(-1280, 0, -100, 700),
            active_monitor_id="left",
            monitors=(left, right),
        )
    )
    service = WindowAvoidanceService(backend, lambda: pet, lambda: True, clock=clock)

    request = _settle(service, clock)

    assert request == MovementRequest((-116, 908), "active_monitor")
    assert request.position[0] < 0


def test_maximised_window_uses_low_obstruction_edge_peek():
    clock = FakeClock()
    monitor = _monitor("main", 0, 0, 1000, 800)
    pet = ScreenRect(800, 600, 900, 700)
    foreground = ScreenRect(0, 0, 1000, 800)
    backend = FakeBackend(
        WindowGeometrySnapshot(
            foreground_hwnd=72,
            foreground_rect=foreground,
            active_monitor_id="main",
            monitors=(monitor,),
        )
    )
    service = WindowAvoidanceService(backend, lambda: pet, lambda: True, clock=clock)

    request = _settle(service, clock)

    assert request == MovementRequest((976, 600), "edge_peek")
    moved = ScreenRect(976, 600, 1076, 700)
    assert moved.intersection_area(foreground) == 24 * 100


def test_drag_rest_and_hidden_gate_all_movement_through_can_move():
    clock = FakeClock()
    blocked = {"dragging": True, "resting": False, "hidden": False}
    monitor = _monitor("main", 0, 0, 1000, 800)
    pet = ScreenRect(700, 600, 800, 700)
    backend = FakeBackend(
        WindowGeometrySnapshot(
            foreground_hwnd=81,
            foreground_rect=ScreenRect(650, 550, 900, 800),
            active_monitor_id="main",
            monitors=(monitor,),
        )
    )
    service = WindowAvoidanceService(
        backend,
        lambda: pet,
        lambda: not any(blocked.values()),
        clock=clock,
    )

    assert service.poll() is None
    assert backend.samples == 0
    clock.advance(10)
    assert service.poll() is None
    assert backend.samples == 0
    blocked["dragging"] = False
    blocked["resting"] = True
    assert service.poll() is None
    assert backend.samples == 0
    blocked["resting"] = False
    blocked["hidden"] = True
    assert service.poll() is None
    assert backend.samples == 0
    blocked["hidden"] = False

    assert _settle(service, clock) == MovementRequest(
        (884, 16),
        "window_avoidance",
    )


def test_minimum_sample_interval_uses_injected_clock_to_throttle_polling():
    clock = FakeClock()
    monitor = _monitor("main", 0, 0, 1000, 800)
    pet = ScreenRect(700, 600, 800, 700)
    backend = FakeBackend(
        WindowGeometrySnapshot(
            foreground_hwnd=82,
            foreground_rect=ScreenRect(0, 0, 300, 300),
            active_monitor_id="main",
            monitors=(monitor,),
        )
    )
    service = WindowAvoidanceService(
        backend,
        lambda: pet,
        lambda: True,
        clock=clock,
        minimum_sample_interval_seconds=2.0,
    )

    assert service.poll() is None
    assert backend.samples == 1
    for _ in range(3):
        clock.advance(0.5)
        assert service.poll() is None
    assert backend.samples == 1

    clock.advance(0.5)
    assert service.poll() is None
    assert backend.samples == 2


def test_request_is_ephemeral_and_does_not_overwrite_permanent_anchor():
    clock = FakeClock()
    anchor = (700, 600)
    pet = ScreenRect(*anchor, 800, 700)
    monitor = _monitor("main", 0, 0, 1000, 800)
    backend = FakeBackend(
        WindowGeometrySnapshot(
            foreground_hwnd=91,
            foreground_rect=ScreenRect(650, 550, 900, 800),
            active_monitor_id="main",
            monitors=(monitor,),
        )
    )
    service = WindowAvoidanceService(backend, lambda: pet, lambda: True, clock=clock)

    request = _settle(service, clock)

    assert request is not None
    assert anchor == (700, 600)
    assert pet == ScreenRect(700, 600, 800, 700)
    assert [field.name for field in fields(MovementRequest)] == ["position", "reason"]


def test_disabling_follow_active_monitor_leaves_non_intersecting_pet_in_place():
    clock = FakeClock()
    left = _monitor("left", -1280, 0, 0, 1024)
    right = _monitor("right", 0, 0, 1920, 1080)
    pet = ScreenRect(1700, 900, 1800, 1000)
    backend = FakeBackend(
        WindowGeometrySnapshot(
            foreground_hwnd=99,
            foreground_rect=ScreenRect(-1200, 100, -400, 700),
            active_monitor_id="left",
            monitors=(left, right),
        )
    )
    service = WindowAvoidanceService(
        backend,
        lambda: pet,
        lambda: True,
        follow_active_monitor=lambda: False,
        clock=clock,
    )

    assert _settle(service, clock) is None


def test_disabling_window_avoidance_does_not_disable_active_monitor_following():
    clock = FakeClock()
    left = _monitor("left", -1280, 0, 0, 1024)
    right = _monitor("right", 0, 0, 1920, 1080)
    pet = ScreenRect(1700, 900, 1800, 1000)
    backend = FakeBackend(
        WindowGeometrySnapshot(
            foreground_hwnd=109,
            foreground_rect=ScreenRect(-1280, 0, -100, 700),
            active_monitor_id="left",
            monitors=(left, right),
        )
    )
    service = WindowAvoidanceService(
        backend,
        lambda: pet,
        lambda: True,
        follow_active_monitor=lambda: True,
        avoid_windows=lambda: False,
        clock=clock,
    )

    request = _settle(service, clock)

    assert request == MovementRequest((-116, 908), "active_monitor")


def test_disabling_window_avoidance_blocks_only_same_monitor_intersection():
    clock = FakeClock()
    monitor = _monitor("main", 0, 0, 1000, 800)
    pet = ScreenRect(700, 600, 800, 700)
    backend = FakeBackend(
        WindowGeometrySnapshot(
            foreground_hwnd=110,
            foreground_rect=ScreenRect(650, 550, 900, 800),
            active_monitor_id="main",
            monitors=(monitor,),
        )
    )
    service = WindowAvoidanceService(
        backend,
        lambda: pet,
        lambda: True,
        avoid_windows=lambda: False,
        clock=clock,
    )

    assert _settle(service, clock) is None


def test_foreground_or_monitor_change_restarts_stability_window():
    clock = FakeClock()
    monitor = _monitor("main", 0, 0, 1000, 800)
    pet = ScreenRect(700, 600, 800, 700)
    backend = FakeBackend(
        WindowGeometrySnapshot(
            foreground_hwnd=100,
            foreground_rect=ScreenRect(650, 550, 900, 800),
            active_monitor_id="main",
            monitors=(monitor,),
        )
    )
    service = WindowAvoidanceService(backend, lambda: pet, lambda: True, clock=clock)

    assert service.poll() is None
    clock.advance(1.5)
    backend.snapshot = WindowGeometrySnapshot(
        foreground_hwnd=101,
        foreground_rect=backend.snapshot.foreground_rect,
        active_monitor_id="main",
        monitors=(monitor,),
    )
    assert service.poll() is None
    clock.advance(1.9)
    assert service.poll() is None
    clock.advance(0.1)
    assert service.poll() == MovementRequest((884, 16), "window_avoidance")


def test_qt_backend_maps_150_percent_physical_pixels_to_logical_coordinates():
    native_monitor = MonitorGeometry(
        "main",
        ScreenRect(0, 0, 1920, 1080),
        r"\\.\DISPLAY1",
    )
    native = FakeBackend(
        WindowGeometrySnapshot(
            foreground_hwnd=120,
            foreground_rect=ScreenRect(960, 270, 1920, 1080),
            active_monitor_id="main",
            monitors=(native_monitor,),
        )
    )
    screen = FakeScreen("DISPLAY1", QRect(0, 0, 1280, 720))

    snapshot = QtLogicalWindowGeometryBackend(
        native,
        screens=lambda: (screen,),
    ).sample()

    assert snapshot.monitors == (
        MonitorGeometry(
            "main",
            ScreenRect(0, 0, 1280, 720),
            r"\\.\DISPLAY1",
        ),
    )
    assert snapshot.foreground_rect == ScreenRect(640, 180, 1280, 720)
    assert snapshot.active_monitor_id == "main"


def test_qt_backend_maps_mixed_200_and_150_percent_negative_desktop():
    left = MonitorGeometry(
        "left",
        ScreenRect(-2560, 0, 0, 1440),
        r"\\.\DISPLAY1",
    )
    right = MonitorGeometry(
        "right",
        ScreenRect(0, 0, 1920, 1080),
        r"\\.\DISPLAY2",
    )
    native = FakeBackend(
        WindowGeometrySnapshot(
            foreground_hwnd=121,
            foreground_rect=ScreenRect(-200, 150, 300, 450),
            active_monitor_id="right",
            monitors=(left, right),
        )
    )
    screens = (
        FakeScreen("DISPLAY1", QRect(-1280, 0, 1280, 720)),
        FakeScreen(r"\\.\DISPLAY2", QRect(0, 0, 1280, 720)),
    )

    snapshot = QtLogicalWindowGeometryBackend(
        native,
        screens=lambda: screens,
    ).sample()

    assert tuple(monitor.work_area for monitor in snapshot.monitors) == (
        ScreenRect(-1280, 0, 0, 720),
        ScreenRect(0, 0, 1280, 720),
    )
    assert snapshot.foreground_rect == ScreenRect(-100, 75, 200, 300)
    assert snapshot.foreground_rects == (
        ScreenRect(-100, 75, 0, 225),
        ScreenRect(0, 100, 200, 300),
    )
    assert snapshot.active_monitor_id == "right"


def test_qt_backend_mapping_failure_disables_movement_geometry_safely():
    native = FakeBackend(
        WindowGeometrySnapshot(
            foreground_hwnd=122,
            foreground_rect=ScreenRect(0, 0, 1920, 1080),
            active_monitor_id="native",
            monitors=(
                MonitorGeometry(
                    "native",
                    ScreenRect(0, 0, 1920, 1080),
                    r"\\.\MISSING",
                ),
            ),
        )
    )
    screen = FakeScreen("DISPLAY1", QRect(0, 0, 1280, 720))

    snapshot = QtLogicalWindowGeometryBackend(
        native,
        screens=lambda: (screen,),
    ).sample()

    assert snapshot.foreground_hwnd == 122
    assert snapshot.foreground_rect is None
    assert snapshot.active_monitor_id is None
    assert snapshot.monitors == ()
    assert not snapshot.geometry_available


def test_temporary_move_keeps_testing_anchor_and_does_not_oscillate():
    clock = FakeClock()
    monitor = _monitor("main", 0, 0, 1000, 800)
    anchor = ScreenRect(700, 600, 800, 700)
    current = {"rect": anchor}
    backend = FakeBackend(
        WindowGeometrySnapshot(
            foreground_hwnd=130,
            foreground_rect=ScreenRect(650, 550, 900, 800),
            active_monitor_id="main",
            monitors=(monitor,),
        )
    )
    service = WindowAvoidanceService(
        backend,
        lambda: current["rect"],
        lambda: True,
        anchor_rect=lambda: anchor,
        clock=clock,
    )
    moves = []
    restores = []

    def apply_temporary_move(request: MovementRequest) -> None:
        moves.append(request)
        x, y = request.position
        current["rect"] = ScreenRect(x, y, x + anchor.width, y + anchor.height)

    service.move_requested.connect(apply_temporary_move)
    service.restore_requested.connect(lambda: restores.append(True))

    assert _settle(service, clock) == MovementRequest(
        (884, 16),
        "window_avoidance",
    )
    for _ in range(5):
        clock.advance(1)
        assert service.poll() is None

    assert len(moves) == 1
    assert restores == []
    assert service.temporarily_displaced


def test_window_moving_off_anchor_requests_one_restore_only():
    clock = FakeClock()
    monitor = _monitor("main", 0, 0, 1000, 800)
    anchor = ScreenRect(700, 600, 800, 700)
    current = {"rect": anchor}
    backend = FakeBackend(
        WindowGeometrySnapshot(
            foreground_hwnd=131,
            foreground_rect=ScreenRect(650, 550, 900, 800),
            active_monitor_id="main",
            monitors=(monitor,),
        )
    )
    service = WindowAvoidanceService(
        backend,
        lambda: current["rect"],
        lambda: True,
        anchor_rect=lambda: anchor,
        clock=clock,
    )
    restores = []
    service.move_requested.connect(
        lambda request: current.update(
            rect=ScreenRect(
                request.position[0],
                request.position[1],
                request.position[0] + anchor.width,
                request.position[1] + anchor.height,
            )
        )
    )
    service.restore_requested.connect(lambda: restores.append(True))
    assert _settle(service, clock) is not None

    backend.snapshot = WindowGeometrySnapshot(
        foreground_hwnd=131,
        foreground_rect=ScreenRect(0, 0, 300, 300),
        active_monitor_id="main",
        monitors=(monitor,),
    )
    clock.advance(1)
    assert service.poll() is None
    clock.advance(1)
    assert service.poll() is None

    assert restores == [True]
    assert not service.temporarily_displaced


def test_user_dragged_anchor_becomes_new_anchor_without_restore_request():
    clock = FakeClock()
    monitor = _monitor("main", 0, 0, 1000, 800)
    anchor = {"rect": ScreenRect(700, 600, 800, 700)}
    current = {"rect": anchor["rect"]}
    backend = FakeBackend(
        WindowGeometrySnapshot(
            foreground_hwnd=132,
            foreground_rect=ScreenRect(650, 550, 900, 800),
            active_monitor_id="main",
            monitors=(monitor,),
        )
    )
    service = WindowAvoidanceService(
        backend,
        lambda: current["rect"],
        lambda: True,
        anchor_rect=lambda: anchor["rect"],
        clock=clock,
    )
    restores = []

    def move(request: MovementRequest) -> None:
        x, y = request.position
        current["rect"] = ScreenRect(x, y, x + 100, y + 100)

    service.move_requested.connect(move)
    service.restore_requested.connect(lambda: restores.append(True))
    assert _settle(service, clock) is not None

    anchor["rect"] = current["rect"]
    backend.snapshot = WindowGeometrySnapshot(
        foreground_hwnd=132,
        foreground_rect=ScreenRect(0, 0, 300, 300),
        active_monitor_id="main",
        monitors=(monitor,),
    )
    clock.advance(1)
    assert service.poll() is None

    assert restores == []
    assert not service.temporarily_displaced


def test_active_monitor_return_requests_restore_to_original_anchor_once():
    clock = FakeClock()
    left = _monitor("left", -1280, 0, 0, 1024)
    right = _monitor("right", 0, 0, 1920, 1080)
    anchor = ScreenRect(1700, 900, 1800, 1000)
    current = {"rect": anchor}
    backend = FakeBackend(
        WindowGeometrySnapshot(
            foreground_hwnd=133,
            foreground_rect=ScreenRect(-1280, 0, -100, 700),
            active_monitor_id="left",
            monitors=(left, right),
        )
    )
    service = WindowAvoidanceService(
        backend,
        lambda: current["rect"],
        lambda: True,
        anchor_rect=lambda: anchor,
        clock=clock,
    )
    restores = []

    def move(request: MovementRequest) -> None:
        x, y = request.position
        current["rect"] = ScreenRect(x, y, x + 100, y + 100)

    service.move_requested.connect(move)
    service.restore_requested.connect(lambda: restores.append(True))
    assert _settle(service, clock) is not None

    backend.snapshot = WindowGeometrySnapshot(
        foreground_hwnd=133,
        foreground_rect=ScreenRect(0, 0, 500, 500),
        active_monitor_id="right",
        monitors=(left, right),
    )
    assert service.poll() is None
    clock.advance(2)
    assert service.poll() is None
    assert restores == [True]
    assert service.poll() is None
    assert restores == [True]


def test_stop_can_request_restore_once_and_clear_temporary_state():
    clock = FakeClock()
    monitor = _monitor("main", 0, 0, 1000, 800)
    anchor = ScreenRect(700, 600, 800, 700)
    backend = FakeBackend(
        WindowGeometrySnapshot(
            foreground_hwnd=134,
            foreground_rect=ScreenRect(650, 550, 900, 800),
            active_monitor_id="main",
            monitors=(monitor,),
        )
    )
    service = WindowAvoidanceService(
        backend,
        lambda: anchor,
        lambda: True,
        anchor_rect=lambda: anchor,
        clock=clock,
    )
    restores = []
    service.restore_requested.connect(lambda: restores.append(True))
    assert _settle(service, clock) is not None

    service.stop(restore=True)
    service.stop(restore=True)

    assert restores == [True]
    assert not service.temporarily_displaced


def test_geometry_failure_preserves_temporary_position_and_never_restores():
    clock = FakeClock()
    monitor = _monitor("main", 0, 0, 1000, 800)
    anchor = ScreenRect(700, 600, 800, 700)
    current = {"rect": anchor}
    normal = WindowGeometrySnapshot(
        foreground_hwnd=140,
        foreground_rect=ScreenRect(650, 550, 900, 800),
        active_monitor_id="main",
        monitors=(monitor,),
    )
    backend = FakeBackend(normal)
    service = WindowAvoidanceService(
        backend,
        lambda: current["rect"],
        lambda: True,
        anchor_rect=lambda: anchor,
        clock=clock,
    )
    restores = []

    def move(request: MovementRequest) -> None:
        x, y = request.position
        current["rect"] = ScreenRect(x, y, x + 100, y + 100)

    service.move_requested.connect(move)
    service.restore_requested.connect(lambda: restores.append(True))
    assert _settle(service, clock) is not None

    backend.snapshot = WindowGeometrySnapshot(geometry_available=False)
    for _ in range(4):
        clock.advance(1)
        assert service.poll() is None

    assert service.temporarily_displaced
    assert restores == []


def test_offscreen_anchor_migrates_to_active_monitor_instead_of_being_misclassified():
    clock = FakeClock()
    monitor = _monitor("main", 0, 0, 1000, 800)
    anchor = ScreenRect(-5000, -5000, -4900, -4900)
    backend = FakeBackend(
        WindowGeometrySnapshot(
            foreground_hwnd=141,
            foreground_rect=None,
            active_monitor_id="main",
            monitors=(monitor,),
        )
    )
    service = WindowAvoidanceService(
        backend,
        lambda: anchor,
        lambda: True,
        anchor_rect=lambda: anchor,
        follow_active_monitor=lambda: True,
        clock=clock,
    )

    request = _settle(service, clock)

    assert request == MovementRequest((16, 16), "active_monitor")


def test_confirmed_temporary_target_is_reissued_after_external_motion():
    clock = FakeClock()
    monitor = _monitor("main", 0, 0, 1000, 800)
    anchor = ScreenRect(700, 600, 800, 700)
    current = {"rect": anchor}
    backend = FakeBackend(
        WindowGeometrySnapshot(
            foreground_hwnd=142,
            foreground_rect=ScreenRect(650, 550, 900, 800),
            active_monitor_id="main",
            monitors=(monitor,),
        )
    )
    service = WindowAvoidanceService(
        backend,
        lambda: current["rect"],
        lambda: True,
        anchor_rect=lambda: anchor,
        clock=clock,
    )
    moves = []

    def move(request: MovementRequest) -> None:
        moves.append(request)
        x, y = request.position
        current["rect"] = ScreenRect(x, y, x + 100, y + 100)

    service.move_requested.connect(move)
    expected = _settle(service, clock)
    assert expected is not None
    current["rect"] = ScreenRect(500, 400, 600, 500)

    clock.advance(1)
    assert service.poll() == expected
    assert moves == [expected, expected]


def test_per_monitor_foreground_parts_avoid_bounding_box_false_positive():
    clock = FakeClock()
    left = _monitor("left", -1280, 0, 0, 720)
    right = _monitor("right", 0, 200, 1280, 920)
    anchor = ScreenRect(-150, 250, -50, 350)
    backend = FakeBackend(
        WindowGeometrySnapshot(
            foreground_hwnd=143,
            foreground_rect=ScreenRect(-200, 200, 200, 720),
            foreground_rects=(
                ScreenRect(-200, 500, 0, 720),
                ScreenRect(0, 200, 200, 400),
            ),
            active_monitor_id="left",
            monitors=(left, right),
        )
    )
    service = WindowAvoidanceService(
        backend,
        lambda: anchor,
        lambda: True,
        anchor_rect=lambda: anchor,
        clock=clock,
    )

    assert anchor.intersects(backend.snapshot.foreground_rect)
    assert _settle(service, clock) is None


def test_ignored_own_window_cannot_drive_avoidance_or_monitor_migration(monkeypatch):
    monitor = MonitorGeometry(
        "main",
        ScreenRect(0, 0, 1000, 800),
        "DISPLAY1",
    )
    fake_api = SimpleNamespace(GetForegroundWindow=lambda: 77)
    monkeypatch.setattr(geometry_module, "api", fake_api)
    backend = Win32WindowGeometryBackend(ignored_hwnds=lambda: {77})
    monkeypatch.setattr(backend, "_monitors", lambda: (monitor,))

    snapshot = backend.sample()

    assert snapshot.foreground_hwnd == 0
    assert snapshot.foreground_rect is None
    assert snapshot.active_monitor_id is None
    assert snapshot.monitors == (monitor,)
    assert not snapshot.geometry_available


def test_own_window_foreground_preserves_existing_temporary_displacement():
    clock = FakeClock()
    monitor = _monitor("main", 0, 0, 1000, 800)
    anchor = ScreenRect(700, 600, 800, 700)
    current = {"rect": anchor}
    backend = FakeBackend(
        WindowGeometrySnapshot(
            foreground_hwnd=150,
            foreground_rect=ScreenRect(650, 550, 900, 800),
            active_monitor_id="main",
            monitors=(monitor,),
        )
    )
    service = WindowAvoidanceService(
        backend,
        lambda: current["rect"],
        lambda: True,
        anchor_rect=lambda: anchor,
        clock=clock,
    )
    restores = []

    def move(request: MovementRequest) -> None:
        x, y = request.position
        current["rect"] = ScreenRect(x, y, x + 100, y + 100)

    service.move_requested.connect(move)
    service.restore_requested.connect(lambda: restores.append(True))
    assert _settle(service, clock) is not None

    backend.snapshot = WindowGeometrySnapshot(geometry_available=False)
    for _ in range(3):
        clock.advance(1)
        assert service.poll() is None

    assert service.temporarily_displaced
    assert restores == []
