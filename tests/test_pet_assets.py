import json
from pathlib import Path

from PIL import Image, ImageDraw

from scripts.build_pet_assets import _FRAME_NAMES, split_sheet


ROOT = Path(__file__).resolve().parents[1]
PET_ROOT = ROOT / 'assets' / 'pets' / 'snow_ferret'


def _border_is_transparent(alpha: Image.Image, margin: int) -> bool:
    width, height = alpha.size
    bands = (
        alpha.crop((0, 0, width, margin)),
        alpha.crop((0, height - margin, width, height)),
        alpha.crop((0, 0, margin, height)),
        alpha.crop((width - margin, 0, width, height)),
    )
    return all(band.getbbox() is None for band in bands)


def _rgba_pixels(image: Image.Image) -> tuple[tuple[int, int, int, int], ...]:
    data = image.convert('RGBA').tobytes()
    return tuple(zip(data[0::4], data[1::4], data[2::4], data[3::4]))


def test_official_frames_have_rgba_content_and_safe_transparent_border():
    for name in _FRAME_NAMES:
        with Image.open(PET_ROOT / 'sprites' / f'{name}.png') as frame:
            assert frame.mode == 'RGBA'
            assert frame.size == (256, 256)
            alpha = frame.getchannel('A')
            assert alpha.getbbox() is not None
            assert _border_is_transparent(alpha, 16)

    with Image.open(PET_ROOT / 'preview.png') as preview:
        assert preview.mode == 'RGBA'
        assert preview.size == (512, 512)
        assert preview.getchannel('A').getbbox() is not None
        assert _border_is_transparent(preview.getchannel('A'), 32)

    with Image.open(PET_ROOT / 'sprites' / 'ferret_atlas_2x.png') as atlas:
        assert atlas.mode == 'RGBA'
        assert atlas.size == (1536, 1536)
        for index in range(16):
            row, column = divmod(index, 4)
            cell = atlas.crop(
                (
                    column * 384,
                    row * 384,
                    (column + 1) * 384,
                    (row + 1) * 384,
                )
            )
            assert cell.getchannel('A').getbbox() is not None
            assert _border_is_transparent(cell.getchannel('A'), 20)


def test_official_walk_action_uses_two_distinct_animation_frames():
    manifest = json.loads((PET_ROOT / 'manifest.json').read_text(encoding='utf-8'))
    frames = manifest['actions']['move']['frames']

    assert manifest['actions']['move']['loop'] is True
    assert len(frames) >= 2
    assert len({tuple(frame['source_rect']) for frame in frames}) == len(frames)

    with Image.open(PET_ROOT / frames[0]['path']) as atlas:
        crops = []
        for frame in frames:
            left, top, width, height = frame['source_rect']
            crops.append(
                atlas.crop((left, top, left + width, top + height)).tobytes()
            )
    assert len(set(crops)) == len(crops)


def test_non_divisible_sheet_assigns_boundary_overflow_to_the_right_pose(tmp_path):
    source = Image.new('RGBA', (125, 125), (0, 0, 0, 0))
    draw = ImageDraw.Draw(source)
    edges = [round(index * 125 / 4) for index in range(5)]
    for index in range(16):
        row, column = divmod(index, 4)
        left = edges[column] + 8
        top = edges[row] + 8
        draw.rectangle((left, top, left + 8, top + 8), fill=(40, 190, 80, 255))

    # The first pose intentionally crosses the rounded row boundary. A naive
    # cell crop leaves its red pixels in both the first and fifth frames.
    draw.rectangle((8, 8, 20, 34), fill=(230, 40, 40, 255))
    draw.rectangle((8, 40, 20, 52), fill=(40, 80, 230, 255))
    source_path = tmp_path / 'sheet.png'
    output = tmp_path / 'pet' / 'sprites'
    source.save(source_path)

    split_sheet(
        source_path,
        output,
        64,
        safe_margin=6,
        alpha_threshold=16,
        min_component_area=8,
        matte_radius=1,
    )

    with Image.open(output / 'idle.png') as first:
        first_pixels = _rgba_pixels(first)
        assert any(alpha > 8 and red > blue for red, _, blue, alpha in first_pixels)
    with Image.open(output / 'walk_1.png') as fifth:
        fifth_pixels = _rgba_pixels(fifth)
        assert any(alpha > 8 and blue > red for red, _, blue, alpha in fifth_pixels)
        assert not any(alpha > 8 and red > blue for red, _, blue, alpha in fifth_pixels)
        assert _border_is_transparent(fifth.getchannel('A'), 6)
