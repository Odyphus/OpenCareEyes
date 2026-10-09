"""Check the completed character and the actual baked frame connections."""

import json
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw
import pytest

from scripts.companion_mesh import CoherentRig


ROOT = Path(__file__).resolve().parents[1]
PET = ROOT / 'assets/pets/snow_ferret'
ACTIONS = ('idle', 'move', 'click_reaction', 'play', 'drag_hold', 'drag_release',
           'right_click_reaction', 'rest_prompt', 'yawn', 'look_left', 'look_center', 'look_right')


def test_blink_keeps_the_neck_shoulders_and_body_pixels_unchanged(qtbot):
    rig = CoherentRig()
    for scarf in (False, True):
        original = rig.textures['head', scarf]
        for expression in ('half', 'closed'):
            delta = ImageChops.difference(original, rig.textures[expression, scarf])
            # Everything below the face must use the exact neutral pixels.
            for channel in delta.split():
                assert channel.crop((0, 145, 384, 384)).getbbox() is None
            assert delta.convert('RGB').getbbox() is not None


@pytest.mark.parametrize('action', ACTIONS)
def test_shared_mesh_boundaries_stay_continuous_and_do_not_fold(action):
    for phase in (0, 0.25, 0.5, 0.75, 1):
        tiles = CoherentRig.mesh(action, phase)
        for index, (box, quad) in enumerate(tiles):
            vertices = list(zip(quad[::2], quad[1::2]))
            area = -sum(x * ny - nx * y for (x, y), (nx, ny)
                        in zip(vertices, vertices[1:] + vertices[:1])) / 2
            assert area > (box[2] - box[0]) * (box[3] - box[1]) * 0.5
            if box[2] < 384:
                neighbor = tiles[index + 1][1]
                assert quad[6:8] == neighbor[0:2]
                assert quad[4:6] == neighbor[2:4]
            if box[3] < 384:
                neighbor = tiles[index + 24][1]
                assert quad[2:4] == neighbor[0:2]
                assert quad[4:6] == neighbor[6:8]


def test_baked_neck_and_forepaws_belong_to_the_same_solid_body():
    manifest = json.loads((PET / 'manifest.json').read_text(encoding='utf-8'))
    atlases = {}
    checked = 0
    for actions in (manifest['actions'], manifest['outfits']['navy_scarf']['actions']):
        for name, action in actions.items():
            if name not in {'click_reaction', 'play'}:
                continue
            for frame in action['frames']:
                path = frame['path']
                if path not in atlases:
                    with Image.open(PET / path) as image:
                        atlases[path] = image.convert('RGBA')
                x, y, w, h = frame['source_rect']
                image = atlases[path].crop((x, y, x + w, y + h))
                alpha = image.getchannel('A')
                if name == 'play':
                    # The green ball is a separate prop. It must not mask a
                    # disconnected white paw, head, neck or charcoal tail.
                    pixels = image.getdata()
                    alpha.putdata([0 if g > r + 12 and g > b + 5 else a
                                   for r, g, b, a in pixels])
                solid = alpha.point(lambda a: 255 if a >= 192 else 0)
                component = solid.copy()
                # The natural low walking torso lies below the upright pose.
                seed = (192, 295) if name == 'move' else (192, 250)
                assert component.getpixel(seed) == 255, name
                ImageDraw.floodfill(component, seed, 64)
                histogram = component.histogram()
                # Check the entire animal, irrespective of a raised paw or
                # lifted foot changing its location. Tiny fur anti-alias specks
                # and the drawn wave marks may be separate; a limb cannot be.
                assert histogram[64] > (12000 if name == 'move' else 20000), name
                assert histogram[255] <= 96, (name, path, histogram[255])
                checked += 1
    assert checked >= 60


def test_jump_is_visible_at_desktop_size_and_returns_to_ground():
    manifest = json.loads((PET / 'manifest.json').read_text(encoding='utf-8'))
    bottoms = []
    for frame in manifest['actions']['click_reaction']['frames']:
        with Image.open(PET / frame['path']) as atlas:
            x, y, w, h = frame['source_rect']
            alpha = atlas.crop((x, y, x + w, y + h)).convert('RGBA').getchannel('A')
        bottoms.append(alpha.point(lambda a: 255 if a >= 192 else 0).getbbox()[3])
    assert max(bottoms) - min(bottoms) >= 18
    assert abs(bottoms[0] - bottoms[-1]) <= 1
