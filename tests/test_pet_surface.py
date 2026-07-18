'''Tests for the stable transparent desktop pet surface.'''

from types import SimpleNamespace

from PySide6.QtCore import (
    QAbstractAnimation,
    QObject,
    QPoint,
    QPointF,
    Signal,
    Qt,
)
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QSignalSpy

from opencareyes.ui.pet_surface import PetSurface


class _DeferredRepository(QObject):
    resource_ready = Signal(str, str)
    resource_failed = Signal(str, str)

    def __init__(self):
        super().__init__()
        self.frames = {}
        self.calls = []

    def load_frame(self, pet_id, resource_path):
        key = (str(pet_id), str(resource_path))
        self.calls.append(key)
        image = self.frames.get(key)
        return QImage(image) if isinstance(image, QImage) else None


def _color_image(color: str) -> QImage:
    image = QImage(8, 8, QImage.Format_ARGB32_Premultiplied)
    image.fill(QColor(color))
    return image


def _manifest():
    missing = SimpleNamespace(path='not-present.png', duration_ms=20)
    idle = SimpleNamespace(action_id='idle', frames=(missing,), loop=True)
    click = SimpleNamespace(action_id='click_reaction', frames=(missing,), loop=False)
    return SimpleNamespace(
        canvas_size=(96, 112),
        actions={'idle': idle, 'click_reaction': click},
        event_bindings={'click': 'click_reaction'},
    )


def _pack(canvas=(96, 112)):
    missing = SimpleNamespace(path='not-present.png', duration_ms=20)
    idle = SimpleNamespace(action_id='idle', frames=(missing,), loop=True)
    return SimpleNamespace(
        canvas_size=canvas,
        actions={'idle': idle},
        event_bindings={},
    )


def test_surface_is_stable_transparent_tool_with_static_fallback(qtbot):
    surface = PetSurface()
    qtbot.addWidget(surface)

    assert surface.windowFlags() & Qt.Tool
    assert surface.windowFlags() & Qt.WindowStaysOnTopHint
    assert surface.testAttribute(Qt.WA_TranslucentBackground)
    assert surface.testAttribute(Qt.WA_ShowWithoutActivating)

    assert surface.set_pack('snow_ferret', _manifest())
    assert surface.size().width() == 96
    assert surface.size().height() == 112
    assert not surface.has_asset_frame
    surface.show()
    assert surface.isVisible()
    assert not surface.animator.is_running


def test_short_click_and_right_click_emit_semantic_signals(qtbot):
    surface = PetSurface()
    qtbot.addWidget(surface)
    surface.set_pack('snow_ferret', _manifest())
    surface.show()
    short = QSignalSpy(surface.short_clicked)
    bubble = QSignalSpy(surface.bubble_requested)
    right = QSignalSpy(surface.right_clicked)

    qtbot.mouseClick(surface, Qt.LeftButton, pos=QPoint(48, 56))
    assert short.count() == 1
    qtbot.waitUntil(lambda: bubble.count() == 1, timeout=1000)
    assert bubble.count() == 1

    qtbot.mouseClick(surface, Qt.RightButton, pos=QPoint(48, 56))
    assert right.count() == 1


def test_long_press_is_drag_not_short_click(qtbot):
    surface = PetSurface()
    qtbot.addWidget(surface)
    surface.set_pack('snow_ferret', _manifest())
    surface.show()
    started = QSignalSpy(surface.drag_started)
    finished = QSignalSpy(surface.drag_finished)
    short = QSignalSpy(surface.short_clicked)

    qtbot.mousePress(surface, Qt.LeftButton, pos=QPoint(48, 56))
    qtbot.wait(280)
    assert started.count() == 1
    qtbot.mouseRelease(surface, Qt.LeftButton, pos=QPoint(48, 56))

    assert finished.count() == 1
    assert short.count() == 0


def test_hidden_and_reduced_surface_stop_animation(qtbot):
    frame_a = SimpleNamespace(path='not-present-a.png', duration_ms=20)
    frame_b = SimpleNamespace(path='not-present-b.png', duration_ms=20)
    idle = SimpleNamespace(action_id='idle', frames=(frame_a, frame_b), loop=True)
    manifest = SimpleNamespace(
        canvas_size=(96, 112),
        actions={'idle': idle},
        event_bindings={},
    )
    surface = PetSurface()
    qtbot.addWidget(surface)
    surface.set_pack('test_pet', manifest)
    surface.show()
    assert surface.animator.is_running

    surface.set_reduced_motion(True)
    assert not surface.animator.is_running
    surface.set_reduced_motion(False)
    assert surface.animator.is_running

    surface.hide()
    assert not surface.animator.is_running


def test_visible_pack_switch_fades_without_replacing_hwnd(qtbot):
    first = _pack()
    second = _pack((112, 96))
    surface = PetSurface()
    qtbot.addWidget(surface)
    assert surface.set_pack('first_pet', first)
    surface.show()
    hwnd = int(surface.winId())
    switched = QSignalSpy(surface.pack_switched)

    assert surface.set_pack('second_pet', second)
    assert surface._switch_animation.duration() == 160
    assert surface._switch_animation.state() == QAbstractAnimation.Running
    qtbot.waitUntil(lambda: surface._switch_phase == 'idle', timeout=1500)

    assert surface.pet_id == 'second_pet'
    assert surface._manifest is second
    assert (surface.width(), surface.height()) == second.canvas_size
    assert int(surface.winId()) == hwnd
    assert switched.count() == 1
    assert switched.at(0) == ['second_pet']


def test_rapid_switch_keeps_only_latest_target_and_signal(qtbot):
    surface = PetSurface()
    qtbot.addWidget(surface)
    surface.set_pack('first_pet', _pack())
    surface.show()
    switched = QSignalSpy(surface.pack_switched)
    second = _pack((104, 104))
    final = _pack((120, 96))

    surface.set_pack('second_pet', second)
    qtbot.waitUntil(lambda: surface.pet_id == 'second_pet', timeout=1000)
    assert surface._switch_phase == 'fading_in'
    surface.set_pack('final_pet', final)
    qtbot.waitUntil(lambda: surface._switch_phase == 'idle', timeout=2000)

    assert surface.pet_id == 'final_pet'
    assert surface._manifest is final
    assert switched.count() == 1
    assert switched.at(0) == ['final_pet']


def test_hidden_or_reduced_motion_switches_immediately(qtbot):
    surface = PetSurface()
    qtbot.addWidget(surface)
    surface.set_pack('first_pet', _pack())
    switched = QSignalSpy(surface.pack_switched)

    surface.set_pack('hidden_target', _pack((104, 104)))
    assert surface.pet_id == 'hidden_target'
    assert surface._switch_phase == 'idle'
    assert not surface._switch_animation.state() == QAbstractAnimation.Running
    assert switched.at(0) == ['hidden_target']

    surface.show()
    surface.set_reduced_motion(True)
    surface.set_pack('reduced_target', _pack((120, 96)))
    assert surface.pet_id == 'reduced_target'
    assert surface._switch_phase == 'idle'
    assert surface.windowOpacity() == 1.0
    assert switched.at(1) == ['reduced_target']


def test_failed_target_restores_previous_pack_and_emits_failure(qtbot, monkeypatch):
    original = _pack()
    broken = _pack((120, 96))
    broken_action = broken.actions['idle']
    surface = PetSurface()
    qtbot.addWidget(surface)
    surface.set_pack('original_pet', original)
    surface.show()
    hwnd = int(surface.winId())
    original_play = surface.animator.play

    def fail_broken_action(action_id, action=None, *, restart=False):
        if action is broken_action:
            return False
        return original_play(action_id, action, restart=restart)

    monkeypatch.setattr(surface.animator, 'play', fail_broken_action)
    failed = QSignalSpy(surface.pack_switch_failed)
    switched = QSignalSpy(surface.pack_switched)

    assert surface.set_pack('broken_pet', broken)
    qtbot.waitUntil(lambda: surface._switch_phase == 'idle', timeout=1500)

    assert surface.pet_id == 'original_pet'
    assert surface._manifest is original
    assert int(surface.winId()) == hwnd
    assert failed.count() == 1
    assert failed.at(0)[0] == 'broken_pet'
    assert switched.count() == 0


def test_repeated_semantic_event_restarts_finished_reaction(qtbot):
    frame_a = SimpleNamespace(path='not-present-a.png', duration_ms=20)
    frame_b = SimpleNamespace(path='not-present-b.png', duration_ms=20)
    idle = SimpleNamespace(action_id='idle', frames=(frame_a,), loop=True)
    reaction = SimpleNamespace(
        action_id='click_reaction',
        frames=(frame_a, frame_b),
        loop=False,
    )
    manifest = SimpleNamespace(
        canvas_size=(96, 112),
        actions={'idle': idle, 'click_reaction': reaction},
        event_bindings={'click': 'click_reaction'},
    )
    surface = PetSurface()
    qtbot.addWidget(surface)
    surface.set_pack('test_pet', manifest)
    surface.show()

    assert surface.play_event('click')
    surface.animator._advance()
    assert surface.animator.frame_index == 1

    assert surface.play_event('click')
    assert surface.animator.frame_index == 0


def test_scale_survives_pack_switch(qtbot):
    surface = PetSurface()
    qtbot.addWidget(surface)
    surface.set_pack('first_pet', _pack((100, 80)))
    surface.set_scale_percent(150)

    surface.set_pack('second_pet', _pack((120, 90)))

    assert surface.pet_id == 'second_pet'
    assert (surface.width(), surface.height()) == (180, 135)


def test_repeated_scale_is_a_geometry_noop(qtbot, monkeypatch):
    surface = PetSurface()
    qtbot.addWidget(surface)
    surface.set_pack('test_pet', _pack((100, 80)))
    calls = []
    original = surface.setFixedSize

    def record_size(*args):
        calls.append(args)
        original(*args)

    monkeypatch.setattr(surface, 'setFixedSize', record_size)

    surface.set_scale_percent(100)
    surface.set_scale_percent(100)
    assert calls == []

    surface.set_scale_percent(150)
    surface.set_scale_percent(150)
    assert len(calls) == 1
    assert (surface.width(), surface.height()) == (150, 120)


def test_cursor_inside_pet_keeps_current_facing_direction(qtbot):
    surface = PetSurface()
    qtbot.addWidget(surface)
    surface.set_pack('test_pet', _pack())
    surface.move(200, 200)
    surface.show()
    surface.set_facing_direction(-1)

    assert not surface.face_towards_cursor(surface.frameGeometry().center())
    assert surface.facing_direction == -1

    target = QPoint(
        surface.frameGeometry().right() + 24,
        surface.frameGeometry().center().y(),
    )
    assert surface.face_towards_cursor(target)
    assert surface.facing_direction == 1
    assert not surface.face_towards_cursor(target)


def test_facing_direction_keeps_hit_testing_aligned_with_mirrored_frame(qtbot):
    surface = PetSurface()
    qtbot.addWidget(surface)
    surface.setFixedSize(10, 10)
    image = QImage(10, 10, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    image.setPixelColor(1, 5, Qt.white)
    surface._set_frame(image)

    surface.set_facing_direction(-1)
    assert surface._contains_visible_pixel(QPointF(1, 5))
    assert not surface._contains_visible_pixel(QPointF(8, 5))

    surface.set_facing_direction(1)
    assert not surface._contains_visible_pixel(QPointF(1, 5))
    assert surface._contains_visible_pixel(QPointF(8, 5))


def test_repeated_appearance_and_frame_are_paint_noops(qtbot, monkeypatch):
    surface = PetSurface()
    qtbot.addWidget(surface)
    surface.set_pack('test_pet', _pack())
    updates = []
    monkeypatch.setattr(surface, 'update', lambda: updates.append(True))

    appearance = SimpleNamespace(headwear='accessories/hat.png')
    surface.set_appearance(appearance)
    surface.set_appearance(appearance)
    assert updates == [True]

    image = QImage(8, 8, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    surface._set_frame(image)
    surface._set_frame(image)
    assert updates == [True, True]


def test_appearance_uses_shared_repository_and_ignores_stale_pet_result(qtbot):
    repository = _DeferredRepository()
    surface = PetSurface(repository)
    qtbot.addWidget(surface)
    surface.set_pack('first_pet', _pack())
    appearance = SimpleNamespace(headwear='accessories/shared.png')
    surface.set_appearance(appearance)
    assert ('first_pet', 'accessories/shared.png') in repository.calls

    surface.set_pack('second_pet', _pack())
    surface.set_appearance(appearance)
    repository.frames[('first_pet', 'accessories/shared.png')] = _color_image(
        '#FF0000'
    )
    repository.resource_ready.emit('first_pet', 'accessories/shared.png')
    assert surface._appearance_images == ()

    repository.frames[('second_pet', 'accessories/shared.png')] = _color_image(
        '#0000FF'
    )
    repository.resource_ready.emit('second_pet', 'accessories/shared.png')
    assert len(surface._appearance_images) == 1
    assert surface._appearance_images[0].pixelColor(0, 0) == QColor('#0000FF')


def test_presentation_visibility_and_suppression_are_idempotent(qtbot):
    frame_a = SimpleNamespace(path='not-present-a.png', duration_ms=20)
    frame_b = SimpleNamespace(path='not-present-b.png', duration_ms=20)
    idle = SimpleNamespace(action_id='idle', frames=(frame_a, frame_b), loop=True)
    manifest = SimpleNamespace(
        canvas_size=(96, 112),
        actions={'idle': idle},
        event_bindings={},
    )
    surface = PetSurface()
    qtbot.addWidget(surface)
    surface.set_pack('test_pet', manifest)

    assert surface.set_presentation_visible(True)
    assert not surface.set_presentation_visible(True)
    assert surface.isVisible()
    assert surface.animator.is_running

    surface._bubble_timer.start()
    assert surface.set_suppressed(True)
    assert not surface.set_suppressed(True)
    assert not surface.animator.is_running
    assert not surface._bubble_timer.isActive()

    assert surface.set_suppressed(False)
    assert surface.animator.is_running
    assert surface.set_presentation_visible(False)
    assert not surface.set_presentation_visible(False)
    assert not surface.isVisible()
    assert not surface.animator.is_running


def test_hiding_during_fade_in_keeps_applied_appearance(qtbot):
    surface = PetSurface()
    qtbot.addWidget(surface)
    surface.set_pack('first_pet', _pack())
    surface.show()

    surface.set_pack('second_pet', _pack((112, 96)))
    qtbot.waitUntil(
        lambda: surface.pet_id == 'second_pet'
        and surface._switch_phase == 'fading_in',
        timeout=1000,
    )
    surface.set_appearance(SimpleNamespace(headwear='accessories/hat.png'))
    surface.hide()

    assert surface._switch_phase == 'idle'
    assert surface._appearance_paths == ('accessories/hat.png',)


def test_hiding_preview_stops_preview_timer(qtbot):
    surface = PetSurface()
    qtbot.addWidget(surface)
    surface.set_pack('test_pet', _pack())

    surface.preview()
    assert surface._preview_timer.isActive()
    surface.hide()

    assert not surface._preview_timer.isActive()
