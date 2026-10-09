"""Observable regressions for smooth gestures and persistent pointer gaze."""

import json
from pathlib import Path
from types import SimpleNamespace

from PIL import Image
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QImage, QColor
from PySide6.QtTest import QSignalSpy

from opencareyes.ui.pet_surface import PetSurface


PET = Path(__file__).resolve().parents[1] / 'assets/pets/snow_ferret'


def _frame_image(frame):
    x, y, width, height = frame['source_rect']
    with Image.open(PET / frame['path']) as image:
        return image.convert('RGBA').crop((x, y, x + width, y + height))


def _dark_center(image, box):
    x0, y0, x1, y1 = box
    points = [(x, y) for y in range(y0, y1) for x in range(x0, x1)
              if max(image.getpixel((x, y))[:3]) < 55 and image.getpixel((x, y))[3] > 192]
    assert len(points) >= 100
    return tuple(sum(p[axis] for p in points) / len(points) for axis in (0, 1))


def test_greeting_holds_one_face_during_the_two_paw_sweeps():
    manifest = json.loads((PET / 'manifest.json').read_text(encoding='utf-8'))
    for actions in (manifest['actions'], manifest['outfits']['navy_scarf']['actions']):
        frames = actions['rest_prompt']['frames']
        centers = [_dark_center(_frame_image(frame), (195, 75, 268, 143)) for frame in frames[9:24]]
        for axis in (0, 1):
            assert max(p[axis] for p in centers) - min(p[axis] for p in centers) < .6
        assert len(frames) >= 24
        assert not actions['rest_prompt']['loop']


def test_both_base_and_scarf_stretch_have_visible_raised_paw_pads():
    manifest = json.loads((PET / 'manifest.json').read_text(encoding='utf-8'))
    for actions in (manifest['actions'], manifest['outfits']['navy_scarf']['actions']):
        images = [_frame_image(frame) for frame in actions['yawn']['frames']]
        for box in ((74, 95, 122, 165), (271, 95, 327, 165)):
            def pink_count(image):
                return sum(r > g + 25 and r > b + 15 and a >= 192
                           for r, g, b, a in image.crop(box).getdata())
            assert max(map(pink_count, images)) > pink_count(images[0]) + 80
        assert images[0].tobytes() == images[-1].tobytes()


def test_greeting_keeps_the_original_face_and_lower_body_in_every_frame():
    manifest = json.loads((PET / 'manifest.json').read_text(encoding='utf-8'))
    for actions in (manifest['actions'], manifest['outfits']['navy_scarf']['actions']):
        images = [_frame_image(frame) for frame in actions['rest_prompt']['frames']]
        # Both eyes, nose and mouth remain fixed, including the lifting and
        # lowering phases that used to warp the entire character.
        for box in ((145, 78, 251, 166), (0, 281, 384, 384)):
            expected = images[0].crop(box).tobytes()
            assert all(image.crop(box).tobytes() == expected for image in images)
        assert images[0].tobytes() == images[-1].tobytes()


def test_stretch_keeps_hips_feet_tail_and_nose_stable_during_lift_and_recovery():
    manifest = json.loads((PET / 'manifest.json').read_text(encoding='utf-8'))
    for actions in (manifest['actions'], manifest['outfits']['navy_scarf']['actions']):
        clip = actions['yawn']
        images = [_frame_image(frame) for frame in clip['frames']]
        for box in ((0, 281, 384, 384), (180, 136, 206, 164)):
            expected = images[0].crop(box).tobytes()
            assert all(image.crop(box).tobytes() == expected for image in images)
        # A long hold reuses one full pose; the allocated frames instead cover
        # ten visible steps up and ten down, rather than six pose jumps.
        assert clip['frames'][11]['duration_ms'] >= 400
        assert len({image.tobytes() for image in images[:11]}) >= 10
        assert len({image.tobytes() for image in images[12:]}) >= 10


def _tracking_pack():
    frames = []
    for index in range(25):
        image = QImage(32, 32, QImage.Format_RGBA8888)
        image.fill(QColor(index * 9, 80, 120))
        frames.append(SimpleNamespace(image=image, duration_ms=600))
    return SimpleNamespace(canvas_size=(96, 112), event_bindings={}, actions={
        'idle': SimpleNamespace(action_id='idle', frames=(frames[12],), loop=True),
        'look_cursor': SimpleNamespace(action_id='look_cursor', frames=(frames[12],), loop=False),
        'look_grid': SimpleNamespace(action_id='look_grid', frames=tuple(frames), loop=False),
        'rest_prompt': SimpleNamespace(action_id='rest_prompt', frames=tuple(frames[:3]), loop=False),
    })


def test_screen_wide_gaze_eases_holds_and_never_restarts_a_manual_greeting(qtbot):
    surface = PetSurface()
    qtbot.addWidget(surface)
    surface.set_pack('snow_ferret', _tracking_pack())
    surface.show()
    surface.play_action('look_cursor')
    surface.set_gaze_target(1600, -800)
    cells = [surface._gaze_cell]
    for _ in range(24):
        surface._advance_gaze()
        cells.append(surface._gaze_cell)
    assert len(set(cells)) >= 3
    assert surface._gaze_cell == (4, 1)
    assert not surface._gaze_timer.isActive()
    assert not surface.animator.is_running
    for _ in range(5):
        surface.set_gaze_target(1600, -800)
        surface._advance_gaze()
    assert surface._gaze_cell == (4, 1)

    surface.play_action('rest_prompt', restart=True)
    changed = QSignalSpy(surface.animator.action_changed)
    surface.set_gaze_target(-1600, 800)
    surface._advance_gaze()
    assert surface.action_id == 'rest_prompt'
    assert changed.count() == 0
    assert not surface._gaze_timer.isActive()


def test_pointer_noise_at_a_gaze_boundary_does_not_flip_pose(qtbot):
    surface = PetSurface()
    qtbot.addWidget(surface)
    surface.set_pack('snow_ferret', _tracking_pack())
    surface.show()
    surface.play_action('look_cursor')
    changes = QSignalSpy(surface.animator.frame_changed)
    for x in (44, 46, 45, 44, 46) * 4:
        surface.set_gaze_target(x, 0)
        surface._advance_gaze()
    assert surface._gaze_cell == (2, 2)
    assert changes.count() == 0
    surface.set_reduced_motion(True)
    assert not surface._gaze_timer.isActive()
    surface.hide()


def test_click_only_reacts_without_opening_the_retired_status_card(qtbot):
    surface = PetSurface()
    qtbot.addWidget(surface)
    surface.set_pack('snow_ferret', _tracking_pack())
    surface.show()
    bubble = QSignalSpy(surface.bubble_requested)
    clicked = QSignalSpy(surface.short_clicked)
    qtbot.mouseClick(surface, Qt.LeftButton, pos=QPoint(48, 56))
    qtbot.wait(350)
    assert clicked.count() == 1
    assert bubble.count() == 0
    qtbot.mouseClick(surface, Qt.RightButton, pos=QPoint(48, 56))
    assert surface._context_menu.isVisible()
    assert '关闭桌面伙伴' in [a.text() for a in surface._context_menu.actions()]
    qtbot.keyClick(surface._context_menu, Qt.Key_Escape)
