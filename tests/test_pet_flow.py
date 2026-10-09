"""Release baselines and observable desktop companion interactions."""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from PIL import Image
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QImage, QColor
from PySide6.QtTest import QSignalSpy

from opencareyes.ui.pet_surface import PetSurface


ROOT = Path(__file__).resolve().parents[1]
PET = ROOT / 'assets/pets/snow_ferret'
POLICY = ROOT / 'artwork/companion/action-policy-v010b11.json'


def _frame_image(frame):
    with Image.open(PET / frame['path']) as image:
        image = image.convert('RGBA')
        if 'source_rect' in frame:
            x, y, width, height = frame['source_rect']
            image = image.crop((x, y, x + width, y + height))
        return image


@pytest.mark.parametrize('variant', ['base', 'navy_scarf'])
def test_other_actions_keep_the_published_v09_frames_and_timing(variant):
    manifest = json.loads((PET / 'manifest.json').read_text(encoding='utf-8'))
    expected = json.loads(POLICY.read_text(encoding='utf-8'))['variants'][variant]
    actions = manifest['actions'] if variant == 'base' else manifest['outfits'][variant]['actions']
    for name, clip in expected['restored_actions'].items():
        assert actions[name] == clip, name
    assert set(actions) == set(expected['restored_actions']) | {'click_reaction', 'play', 'right_click_reaction'}
    for path, sha256 in expected['restored_assets'].items():
        assert hashlib.sha256((PET / path).read_bytes()).hexdigest() == sha256, path


@pytest.mark.parametrize('variant', ['base', 'navy_scarf'])
def test_accepted_head_pat_and_play_keep_every_b10_pixel_and_duration(variant):
    manifest = json.loads((PET / 'manifest.json').read_text(encoding='utf-8'))
    expected = json.loads(POLICY.read_text(encoding='utf-8'))['variants'][variant]
    actions = manifest['actions'] if variant == 'base' else manifest['outfits'][variant]['actions']
    for name, baseline in expected['preserved_clips'].items():
        clip = actions[name]
        assert clip['loop'] == baseline['loop']
        assert len(clip['frames']) == len(baseline['frames'])
        for frame, original in zip(clip['frames'], baseline['frames']):
            image = _frame_image(frame)
            assert frame['duration_ms'] == original['duration_ms']
            assert list(image.size) == original['size']
            assert hashlib.sha256(image.tobytes()).hexdigest() == original['rgba_sha256']


def test_right_click_is_unbound_and_schema_placeholder_is_neutral():
    manifest = json.loads((PET / 'manifest.json').read_text(encoding='utf-8'))
    assert 'right_click' not in manifest['event_bindings']
    for actions in (manifest['actions'], manifest['outfits']['navy_scarf']['actions']):
        assert actions['right_click_reaction']['frames'] == [actions['idle']['frames'][0]]


def test_rest_scene_static_pet_matches_the_restored_sleep_frame():
    manifest = json.loads((PET / 'manifest.json').read_text(encoding='utf-8'))
    expected = _frame_image(manifest['actions']['sleep']['frames'][0])
    with Image.open(PET / 'rest_sleep.png') as image:
        assert image.convert('RGBA').tobytes() == expected.tobytes()


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
    action_before = surface.action_id
    pet_events = QSignalSpy(surface.pet_event)
    qtbot.mouseClick(surface, Qt.RightButton, pos=QPoint(48, 56))
    assert surface._context_menu.isVisible()
    assert pet_events.count() == 0
    assert surface.action_id == action_before
    assert '关闭桌面伙伴' in [a.text() for a in surface._context_menu.actions()]
    qtbot.keyClick(surface._context_menu, Qt.Key_Escape)
