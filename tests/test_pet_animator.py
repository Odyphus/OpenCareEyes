'''Tests for the shared declarative pet frame clock.'''

from types import SimpleNamespace

from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QSignalSpy

from opencareyes.ui.pet_animator import PetAnimator


def _image(color: str) -> QImage:
    image = QImage(8, 8, QImage.Format_ARGB32_Premultiplied)
    image.fill(QColor(color))
    return image


def _action(*frames: QImage, loop: bool = True):
    wrapped = tuple(
        SimpleNamespace(image=frame, duration_ms=20) for frame in frames
    )
    return SimpleNamespace(action_id='idle', frames=wrapped, loop=loop)


def test_animator_uses_one_clock_and_stops_when_hidden(qtbot):
    animator = PetAnimator()
    frames = QSignalSpy(animator.frame_changed)
    action = _action(_image('#FFFFFF'), _image('#111111'))

    animator.set_surface_visible(True)
    assert animator.play('idle', action)
    assert animator.timer.isSingleShot()
    assert animator.is_running
    assert frames.count() == 1

    animator.set_surface_visible(False)
    assert not animator.is_running

    animator.set_surface_visible(True)
    assert animator.is_running


def test_static_and_reduced_motion_never_leave_frame_clock_running(qtbot):
    animator = PetAnimator()
    animator.set_surface_visible(True)

    assert animator.play('idle', _action(_image('#FFFFFF')))
    assert not animator.is_running

    animated = _action(_image('#FFFFFF'), _image('#111111'))
    assert animator.play('idle', animated, restart=True)
    assert animator.is_running

    animator.set_reduced_motion(True)
    assert not animator.is_running
    assert animator.frame_index == 0

    animator.set_reduced_motion(False)
    assert animator.is_running


def test_repeated_action_does_not_restart_or_publish_semantic_change(qtbot):
    now = [0.0]
    animator = PetAnimator(clock=lambda: now[0])
    changed = QSignalSpy(animator.action_changed)
    action = _action(_image('#FFFFFF'), _image('#111111'))
    animator.set_surface_visible(True)

    assert animator.play('idle', action)
    now[0] = 0.05
    animator._advance()
    assert animator.frame_index == 1

    assert animator.play('idle', action)
    assert animator.frame_index == 1
    assert changed.count() == 1


def test_missing_frame_is_a_safe_static_fallback(qtbot):
    animator = PetAnimator()
    frames = QSignalSpy(animator.frame_changed)
    missing = SimpleNamespace(path='not-present.png', duration_ms=83)
    action = SimpleNamespace(action_id='idle', frames=(missing,), loop=True)

    animator.set_surface_visible(True)
    assert animator.play('idle', action)

    assert frames.count() == 1
    assert frames.at(0) == [None]
    assert not animator.is_running


def test_registry_resolves_pack_relative_frame(qtbot):
    class _Registry:
        calls = []

        def resolve_resource(self, pet_id, resource_path):
            self.calls.append((pet_id, resource_path))
            return 'not-present.png'

    registry = _Registry()
    frame = SimpleNamespace(path='sprites/idle.png', duration_ms=83)
    action = SimpleNamespace(action_id='idle', frames=(frame,), loop=True)
    animator = PetAnimator(registry)
    rendered = QSignalSpy(animator.frame_changed)
    animator.set_pack('snow_ferret', SimpleNamespace(actions={'idle': action}))

    animator.set_surface_visible(True)
    assert animator.play('idle')

    assert registry.calls == [('snow_ferret', 'sprites/idle.png')]
    assert rendered.at(0) == [None]


def test_finished_non_loop_action_does_not_finish_again_after_show(qtbot):
    animator = PetAnimator()
    finished = QSignalSpy(animator.animation_finished)
    action = _action(_image('#FFFFFF'), _image('#111111'), loop=False)
    animator.set_surface_visible(True)

    assert animator.play('reaction', action)
    qtbot.waitUntil(lambda: finished.count() == 1, timeout=1000)
    assert not animator.is_running

    animator.set_surface_visible(False)
    animator.set_surface_visible(True)
    qtbot.wait(80)

    assert finished.count() == 1
    assert not animator.is_running


def test_image_cache_enforces_byte_budget(monkeypatch):
    animator = PetAnimator(cache_limit=64, cache_limit_bytes=300)
    monkeypatch.setattr(animator, '_load_from_repository', lambda _path: _image('#FFFFFF'))

    animator._load_image(SimpleNamespace(path='first.png'))
    animator._load_image(SimpleNamespace(path='second.png'))

    assert len(animator._image_cache) == 1
    assert animator._cache_bytes <= 300


def test_declared_frame_rate_is_capped_without_mutating_frame():
    frame = SimpleNamespace(image=_image('#FFFFFF'), duration_ms=12)

    assert PetAnimator._frame_duration(frame) == 50
    assert frame.duration_ms == 12


def test_monotonic_deadline_skips_expired_frames_without_drift(qtbot):
    now = [0.0]
    animator = PetAnimator(clock=lambda: now[0])
    action = _action(
        _image('#FFFFFF'),
        _image('#DDDDDD'),
        _image('#888888'),
        _image('#111111'),
    )
    animator.set_surface_visible(True)
    assert animator.play('idle', action)

    now[0] = 0.16
    animator._advance()

    assert animator.frame_index == 3
    assert animator._frame_deadline == 0.2

    now[0] = 0.21
    animator._advance()

    assert animator.frame_index == 0
    assert animator._frame_deadline == 0.25


def test_delayed_non_loop_action_finishes_once(qtbot):
    now = [0.0]
    animator = PetAnimator(clock=lambda: now[0])
    finished = QSignalSpy(animator.animation_finished)
    action = _action(_image('#FFFFFF'), _image('#111111'), loop=False)
    animator.set_surface_visible(True)
    assert animator.play('reaction', action)

    now[0] = 5.0
    animator._advance()

    assert animator.frame_index == 1
    assert finished.count() == 1
    assert not animator.is_running


def test_atlas_is_decoded_once_and_crops_are_cached_by_rect_and_dpr(qtbot):
    atlas = QImage(16, 8, QImage.Format_ARGB32_Premultiplied)
    atlas.fill(QColor('#FF0000'))
    for x in range(8, 16):
        for y in range(8):
            atlas.setPixelColor(x, y, QColor('#0000FF'))

    class _Repository:
        def __init__(self):
            self.calls = []

        def load_frame(self, pet_id, path):
            self.calls.append((pet_id, path))
            return atlas

    repository = _Repository()
    animator = PetAnimator(repository)
    animator.set_pack('snow_ferret', SimpleNamespace(actions={}))
    left = SimpleNamespace(
        path='sprites/atlas.png', source_rect=(0, 0, 8, 8), dpr=1.0
    )
    right = SimpleNamespace(
        path='sprites/atlas.png', source_rect=(8, 0, 8, 8), dpr=2.0
    )

    left_image = animator._load_image(left)
    right_image = animator._load_image(right)
    left_again = animator._load_image(left)

    assert repository.calls == [('snow_ferret', 'sprites/atlas.png')]
    assert left_image.pixelColor(0, 0) == QColor('#FF0000')
    assert right_image.pixelColor(0, 0) == QColor('#0000FF')
    assert right_image.devicePixelRatio() == 2.0
    assert left_again.cacheKey() == left_image.cacheKey()
    frame_keys = [key for key in animator._image_cache if key[2] == 'frame']
    assert len(frame_keys) == 2


def test_crop_cache_preserves_atlas_when_budget_only_fits_source(qtbot):
    atlas = _image('#FFFFFF')

    class _Repository:
        calls = 0

        def load_frame(self, _pet_id, _path):
            self.calls += 1
            return atlas

    repository = _Repository()
    animator = PetAnimator(repository, cache_limit=1, cache_limit_bytes=300)
    frame = SimpleNamespace(path='atlas.png', source_rect=(0, 0, 4, 4))

    animator._load_image(frame)
    animator._load_image(frame)

    assert repository.calls == 1
    assert len(animator._image_cache) == 1
    assert next(iter(animator._image_cache))[2] == 'source'
