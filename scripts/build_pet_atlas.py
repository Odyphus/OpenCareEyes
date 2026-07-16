'''Build the deterministic 2x sprite atlas used by the official ferret pack.'''

from __future__ import annotations

from pathlib import Path

from PIL import Image

from build_pet_assets import _FRAME_NAMES


CELL_SIZE = 384
GRID_SIZE = 4


def build_atlas(pet_root: Path) -> Path:
    sprites = pet_root / 'sprites'
    atlas = Image.new(
        'RGBA',
        (CELL_SIZE * GRID_SIZE, CELL_SIZE * GRID_SIZE),
        (0, 0, 0, 0),
    )
    for index, name in enumerate(_FRAME_NAMES):
        with Image.open(sprites / f'{name}.png') as source:
            frame = source.convert('RGBA').resize(
                (CELL_SIZE, CELL_SIZE),
                Image.Resampling.LANCZOS,
            )
        row, column = divmod(index, GRID_SIZE)
        atlas.alpha_composite(frame, (column * CELL_SIZE, row * CELL_SIZE))
    destination = sprites / 'ferret_atlas_2x.png'
    atlas.save(destination, optimize=True)
    return destination


if __name__ == '__main__':
    root = Path(__file__).resolve().parents[1] / 'assets' / 'pets' / 'snow_ferret'
    build_atlas(root)
