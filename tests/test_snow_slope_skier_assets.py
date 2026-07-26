from __future__ import annotations

from pathlib import Path

from PIL import Image
import pytest

from opencareyes.application.pet_pack_registry import PetPackRegistry
from opencareyes.constants import APP_VERSION, PETS_DIR
from scripts.build_snow_slope_skier import (
    FRAME_SOURCES,
    SHEET_SPLITS,
    _validate_no_chroma_spill,
)

REVIEW_ROOT = (
    Path(__file__).parents[1]
    / 'docs'
    / 'design'
    / 'outfits'
    / 'snow_slope_skier'
)
OUTFIT_ROOT = (
    Path(PETS_DIR)
    / 'snow_ferret'
    / 'outfits'
    / 'snow_slope_skier'
)


def test_snow_slope_skier_declares_exactly_29_unique_frames():
    names = [source.name for source in FRAME_SOURCES]

    assert len(names) == 29
    assert len(set(names)) == 29
    assert {source.atlas for source in FRAME_SOURCES} == {1, 2}


def test_snow_slope_skier_rejects_visible_chroma_spill():
    image = Image.new('RGBA', (8, 8), (255, 255, 255, 255))
    for x in range(5):
        for y in range(7):
            image.putpixel((x, y), (241, 7, 212, 255))

    with pytest.raises(ValueError, match='visible magenta spill pixels'):
        _validate_no_chroma_spill(image, 'interaction.png')


def test_snow_slope_skier_accepts_white_fur_and_pink_ear_tones():
    image = Image.new('RGBA', (8, 8), (250, 250, 246, 255))
    image.putpixel((0, 0), (244, 162, 184, 255))

    _validate_no_chroma_spill(image, 'clean.png')


def test_snow_slope_skier_uses_transparent_safe_split_bands():
    for sheet_name, (horizontal, vertical) in SHEET_SPLITS.items():
        with Image.open(REVIEW_ROOT / sheet_name) as opened:
            alpha = opened.convert('RGBA').getchannel('A')
        for x in horizontal[1:-1]:
            assert alpha.crop((x - 2, 0, x + 3, alpha.height)).getbbox() is None
        for y in vertical[1:-1]:
            assert alpha.crop((0, y - 2, alpha.width, y + 3)).getbbox() is None


def test_official_snow_slope_skier_outfit_has_complete_runtime_assets():
    manifest = PetPackRegistry(
        PETS_DIR,
        app_version=APP_VERSION,
    ).load('snow_ferret')
    outfit = manifest.outfits['snow_slope_skier']

    assert set(outfit.actions) == {
        'idle',
        'sleep',
        'move',
        'click_reaction',
        'drag_hold',
        'drag_release',
        'right_click_reaction',
        'rest_prompt',
        'play',
        'look_cursor',
    }
    frames = [
        frame
        for action in outfit.actions.values()
        for frame in action.frames
    ]
    assert len(frames) == 29
    assert len({(frame.path, frame.source_rect) for frame in frames}) == 29

    for atlas_name in (
        'snow_slope_skier_atlas_1.png',
        'snow_slope_skier_atlas_2.png',
    ):
        with Image.open(OUTFIT_ROOT / atlas_name) as atlas:
            assert atlas.mode == 'RGBA'
            assert atlas.size == (1536, 1536)

    assert sum(path.stat().st_size for path in OUTFIT_ROOT.iterdir()) < 5 * 1024 * 1024
