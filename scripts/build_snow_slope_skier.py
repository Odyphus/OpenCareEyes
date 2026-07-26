'''Build the official Snow Slope Skier outfit atlases from reviewed pose sheets.'''

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image


CELL_SIZE = 384
GRID_SIZE = 4
SAFE_MARGIN = 12
MAX_CHROMA_SPILL_PIXELS = 32

SHEET_SPLITS = {
    'sheet_idle_sleep_rgba.png': (
        (0, 464, 883, 1300, 1774),
        (0, 448, 887),
    ),
    'sheet_move_play_rgba.png': (
        (0, 442, 866, 1313, 1774),
        (0, 404, 887),
    ),
    'sheet_click_drag_rgba_offline.png': (
        (0, 456, 880, 1291, 1774),
        (0, 434, 887),
    ),
    'sheet_shy_rest_rgba.png': (
        (0, 513, 999, 1536),
        (0, 497, 1024),
    ),
}


@dataclass(frozen=True)
class FrameSource:
    name: str
    sheet: str
    columns: int
    rows: int
    index: int
    atlas: int


FRAME_SOURCES = (
    FrameSource('idle_1', 'sheet_idle_sleep_rgba.png', 4, 2, 0, 1),
    FrameSource('idle_2', 'sheet_idle_sleep_rgba.png', 4, 2, 1, 1),
    FrameSource('idle_3', 'sheet_idle_sleep_rgba.png', 4, 2, 2, 1),
    FrameSource('sleep_1', 'sheet_idle_sleep_rgba.png', 4, 2, 6, 1),
    FrameSource('sleep_2', 'sheet_idle_sleep_rgba.png', 4, 2, 7, 1),
    FrameSource('move_1', 'sheet_move_play_rgba.png', 4, 2, 0, 1),
    FrameSource('move_2', 'sheet_move_play_rgba.png', 4, 2, 1, 1),
    FrameSource('move_3', 'sheet_move_play_rgba.png', 4, 2, 2, 1),
    FrameSource('move_4', 'sheet_move_play_rgba.png', 4, 2, 3, 1),
    FrameSource('click_1', 'sheet_click_drag_rgba_offline.png', 4, 2, 0, 1),
    FrameSource('click_2', 'sheet_click_drag_rgba_offline.png', 4, 2, 1, 1),
    FrameSource('click_3', 'sheet_click_drag_rgba_offline.png', 4, 2, 2, 1),
    FrameSource('drag_hold', 'sheet_click_drag_rgba_offline.png', 4, 2, 3, 1),
    FrameSource('drag_release_1', 'sheet_click_drag_rgba_offline.png', 4, 2, 4, 1),
    FrameSource('drag_release_2', 'sheet_click_drag_rgba_offline.png', 4, 2, 5, 1),
    FrameSource('drag_release_3', 'sheet_click_drag_rgba_offline.png', 4, 2, 6, 1),
    FrameSource('right_click_1', 'sheet_shy_rest_rgba.png', 3, 2, 0, 2),
    FrameSource('right_click_2', 'sheet_shy_rest_rgba.png', 3, 2, 1, 2),
    FrameSource('right_click_3', 'sheet_shy_rest_rgba.png', 3, 2, 2, 2),
    FrameSource('rest_prompt_1', 'sheet_shy_rest_rgba.png', 3, 2, 3, 2),
    FrameSource('rest_prompt_2', 'sheet_shy_rest_rgba.png', 3, 2, 4, 2),
    FrameSource('rest_prompt_3', 'sheet_shy_rest_rgba.png', 3, 2, 5, 2),
    FrameSource('play_1', 'sheet_move_play_rgba.png', 4, 2, 4, 2),
    FrameSource('play_2', 'sheet_move_play_rgba.png', 4, 2, 5, 2),
    FrameSource('play_3', 'sheet_move_play_rgba.png', 4, 2, 6, 2),
    FrameSource('play_4', 'sheet_move_play_rgba.png', 4, 2, 7, 2),
    FrameSource('look_left', 'sheet_idle_sleep_rgba.png', 4, 2, 3, 2),
    FrameSource('look_center', 'sheet_idle_sleep_rgba.png', 4, 2, 4, 2),
    FrameSource('look_right', 'sheet_idle_sleep_rgba.png', 4, 2, 5, 2),
)


def _cell(image: Image.Image, source: FrameSource) -> Image.Image:
    if not 0 <= source.index < source.columns * source.rows:
        raise ValueError(f'{source.name} frame index is outside its sheet grid')
    row, column = divmod(source.index, source.columns)
    split = SHEET_SPLITS.get(source.sheet)
    if split is None:
        horizontal = tuple(
            round(index * image.width / source.columns)
            for index in range(source.columns + 1)
        )
        vertical = tuple(
            round(index * image.height / source.rows)
            for index in range(source.rows + 1)
        )
    else:
        horizontal, vertical = split
        if (
            len(horizontal) != source.columns + 1
            or len(vertical) != source.rows + 1
            or horizontal[0] != 0
            or vertical[0] != 0
            or horizontal[-1] != image.width
            or vertical[-1] != image.height
            or any(left >= right for left, right in zip(horizontal, horizontal[1:]))
            or any(top >= bottom for top, bottom in zip(vertical, vertical[1:]))
        ):
            raise ValueError(f'{source.sheet} has invalid safe split coordinates')
    left, right = horizontal[column : column + 2]
    top, bottom = vertical[row : row + 2]
    return image.crop((left, top, right, bottom))


def _render_cell(
    cell: Image.Image,
    *,
    nominal_size: tuple[int, int],
) -> Image.Image:
    cell = cell.convert('RGBA')
    if cell.getchannel('A').getbbox() is None:
        raise ValueError('reviewed pose cell has no visible alpha')
    available = CELL_SIZE - SAFE_MARGIN * 2
    scale = min(
        available / nominal_size[0],
        available / nominal_size[1],
    )
    resized = cell.resize(
        (round(cell.width * scale), round(cell.height * scale)),
        Image.Resampling.LANCZOS,
    )
    frame = Image.new('RGBA', (CELL_SIZE, CELL_SIZE), (0, 0, 0, 0))
    frame.alpha_composite(
        resized,
        (
            (CELL_SIZE - resized.width) // 2,
            CELL_SIZE - SAFE_MARGIN - resized.height,
        ),
    )
    return frame


def _validate_no_chroma_spill(image: Image.Image, source_name: str) -> None:
    rgba = image.convert('RGBA')
    flattened = getattr(rgba, 'get_flattened_data', None)
    pixels = flattened() if callable(flattened) else rgba.getdata()
    spill_pixels = sum(
        1
        for red, green, blue, alpha in pixels
        if (
            alpha >= 16
            and red >= 180
            and blue >= 140
            and green <= 90
        )
    )
    if spill_pixels > MAX_CHROMA_SPILL_PIXELS:
        raise ValueError(
            f'{source_name} retains {spill_pixels} visible magenta spill pixels'
        )


def build(review_root: Path, outfit_root: Path) -> dict[str, tuple[int, int, int, int]]:
    sheets: dict[str, Image.Image] = {}
    frames: dict[str, Image.Image] = {}
    for source in FRAME_SOURCES:
        sheet = sheets.get(source.sheet)
        if sheet is None:
            sheet = Image.open(review_root / source.sheet).convert('RGBA')
            _validate_no_chroma_spill(sheet, source.sheet)
            sheets[source.sheet] = sheet
        frames[source.name] = _render_cell(
            _cell(sheet, source),
            nominal_size=(
                round(sheet.width / source.columns),
                round(sheet.height / source.rows),
            ),
        )

    outfit_root.mkdir(parents=True, exist_ok=True)
    frame_rects: dict[str, tuple[int, int, int, int]] = {}
    for atlas_number in (1, 2):
        atlas = Image.new(
            'RGBA',
            (CELL_SIZE * GRID_SIZE, CELL_SIZE * GRID_SIZE),
            (0, 0, 0, 0),
        )
        atlas_sources = [
            source for source in FRAME_SOURCES if source.atlas == atlas_number
        ]
        for index, source in enumerate(atlas_sources):
            row, column = divmod(index, GRID_SIZE)
            rect = (
                column * CELL_SIZE,
                row * CELL_SIZE,
                CELL_SIZE,
                CELL_SIZE,
            )
            atlas.alpha_composite(frames[source.name], rect[:2])
            frame_rects[source.name] = rect
        atlas.save(
            outfit_root / f'snow_slope_skier_atlas_{atlas_number}.png',
            optimize=True,
        )

    idle = frames['idle_1']
    idle.resize((256, 256), Image.Resampling.LANCZOS).save(
        outfit_root / 'thumbnail.png',
        optimize=True,
    )
    idle.resize((512, 512), Image.Resampling.LANCZOS).save(
        outfit_root / 'preview.png',
        optimize=True,
    )
    return frame_rects


if __name__ == '__main__':
    project_root = Path(__file__).resolve().parents[1]
    rects = build(
        project_root / 'docs' / 'design' / 'outfits' / 'snow_slope_skier',
        project_root
        / 'assets'
        / 'pets'
        / 'snow_ferret'
        / 'outfits'
        / 'snow_slope_skier',
    )
    for frame_name, source_rect in rects.items():
        print(frame_name, *source_rect)
