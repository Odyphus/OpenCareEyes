'''Build a standard 29-frame outfit from four reviewed RGBA pose sheets.'''

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from PIL import Image


CELL_SIZE = 384
GRID_SIZE = 4
SAFE_MARGIN = 12
EDGE_FRAGMENT_BAND_RATIO = 0.14
EDGE_FRAGMENT_SIGNIFICANT_RATIO = 0.04


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
    FrameSource('click_1', 'sheet_click_drag_rgba.png', 4, 2, 0, 1),
    FrameSource('click_2', 'sheet_click_drag_rgba.png', 4, 2, 1, 1),
    FrameSource('click_3', 'sheet_click_drag_rgba.png', 4, 2, 2, 1),
    FrameSource('drag_hold', 'sheet_click_drag_rgba.png', 4, 2, 3, 1),
    FrameSource('drag_release_1', 'sheet_click_drag_rgba.png', 4, 2, 4, 1),
    FrameSource('drag_release_2', 'sheet_click_drag_rgba.png', 4, 2, 5, 1),
    FrameSource('drag_release_3', 'sheet_click_drag_rgba.png', 4, 2, 6, 1),
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


def _valley_split(
    values: list[int],
    expected: int,
    radius: int,
    minimum: int,
    maximum: int,
) -> int:
    left = max(minimum, expected - radius)
    right = min(maximum, expected + radius)
    if left >= right:
        raise ValueError('pose sheet has no room for an adaptive grid split')
    return min(range(left, right + 1), key=lambda index: (values[index], abs(index - expected)))


def _cell(image: Image.Image, source: FrameSource) -> Image.Image:
    if not 0 <= source.index < source.columns * source.rows:
        raise ValueError(f'{source.name} frame index is outside its sheet grid')
    row, column = divmod(source.index, source.columns)
    alpha = image.getchannel('A')
    vertical_projection = [
        sum(alpha.crop((0, y, image.width, y + 1)).tobytes())
        for y in range(image.height)
    ]
    vertical = [0]
    nominal_height = image.height / source.rows
    for boundary in range(1, source.rows):
        vertical.append(
            _valley_split(
                vertical_projection,
                round(boundary * nominal_height),
                max(2, round(nominal_height * 0.22)),
                vertical[-1] + 1,
                image.height - (source.rows - boundary),
            )
        )
    vertical.append(image.height)

    top, bottom = vertical[row : row + 2]
    row_alpha = alpha.crop((0, top, image.width, bottom))
    horizontal_projection = [
        sum(row_alpha.crop((x, 0, x + 1, row_alpha.height)).tobytes())
        for x in range(image.width)
    ]
    horizontal = [0]
    nominal_width = image.width / source.columns
    for boundary in range(1, source.columns):
        horizontal.append(
            _valley_split(
                horizontal_projection,
                round(boundary * nominal_width),
                max(2, round(nominal_width * 0.22)),
                horizontal[-1] + 1,
                image.width - (source.columns - boundary),
            )
        )
    horizontal.append(image.width)
    return image.crop(
        (
            horizontal[column],
            top,
            horizontal[column + 1],
            bottom,
        )
    )


def _remove_edge_fragments(cell: Image.Image) -> Image.Image:
    '''Remove only small, detached pose fragments close to a cell boundary.'''
    cell = cell.convert('RGBA')
    alpha = cell.getchannel('A')
    width, height = cell.size
    values = alpha.tobytes()
    visited = bytearray(width * height)
    components: list[tuple[list[int], tuple[int, int, int, int], int]] = []

    for seed, value in enumerate(values):
        if value == 0 or visited[seed]:
            continue
        visited[seed] = 1
        stack = [seed]
        pixels: list[int] = []
        alpha_sum = 0
        left = right = seed % width
        top = bottom = seed // width
        while stack:
            index = stack.pop()
            pixels.append(index)
            alpha_sum += values[index]
            x = index % width
            y = index // width
            left = min(left, x)
            right = max(right, x)
            top = min(top, y)
            bottom = max(bottom, y)
            for neighbor_y in range(max(0, y - 1), min(height, y + 2)):
                row_start = neighbor_y * width
                for neighbor_x in range(max(0, x - 1), min(width, x + 2)):
                    neighbor = row_start + neighbor_x
                    if not visited[neighbor] and values[neighbor] != 0:
                        visited[neighbor] = 1
                        stack.append(neighbor)
        components.append(
            (pixels, (left, top, right + 1, bottom + 1), alpha_sum)
        )

    if len(components) < 2:
        return cell

    primary = max(components, key=lambda component: component[2])
    primary_alpha = primary[2]
    edge_band = max(8, round(min(width, height) * EDGE_FRAGMENT_BAND_RATIO))
    cleaned_alpha = bytearray(values)
    changed = False

    for component in components:
        if component is primary:
            continue
        pixels, box, alpha_sum = component
        left, top, right, bottom = box
        near_edge = (
            left < edge_band
            or top < edge_band
            or right > width - edge_band
            or bottom > height - edge_band
        )
        significant = (
            alpha_sum >= primary_alpha * EDGE_FRAGMENT_SIGNIFICANT_RATIO
        )
        if near_edge and not significant:
            changed = True
            for index in pixels:
                cleaned_alpha[index] = 0

    if changed:
        cell.putalpha(Image.frombytes('L', cell.size, bytes(cleaned_alpha)))
    return cell


def _render_cell(cell: Image.Image) -> Image.Image:
    cell = _remove_edge_fragments(cell)
    content_box = cell.getchannel('A').getbbox()
    if content_box is None:
        raise ValueError('reviewed pose cell has no visible alpha')
    content = cell.crop(content_box)
    available = CELL_SIZE - SAFE_MARGIN * 2
    scale = min(available / content.width, available / content.height, 1.0)
    rendered = content.resize(
        (
            max(1, round(content.width * scale)),
            max(1, round(content.height * scale)),
        ),
        Image.Resampling.LANCZOS,
    )
    frame = Image.new('RGBA', (CELL_SIZE, CELL_SIZE), (0, 0, 0, 0))
    frame.alpha_composite(
        rendered,
        (
            (CELL_SIZE - rendered.width) // 2,
            CELL_SIZE - SAFE_MARGIN - rendered.height,
        ),
    )
    return frame


def build(
    review_root: Path,
    outfit_root: Path,
    outfit_id: str,
) -> dict[str, tuple[int, int, int, int]]:
    sheets: dict[str, Image.Image] = {}
    frames: dict[str, Image.Image] = {}
    for source in FRAME_SOURCES:
        sheet = sheets.get(source.sheet)
        if sheet is None:
            path = review_root / source.sheet
            if not path.is_file():
                raise FileNotFoundError(path)
            sheet = Image.open(path).convert('RGBA')
            sheets[source.sheet] = sheet
        frames[source.name] = _render_cell(_cell(sheet, source))

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
            outfit_root / f'{outfit_id}_atlas_{atlas_number}.png',
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('outfit_id')
    parser.add_argument('--review-root', required=True, type=Path)
    parser.add_argument('--outfit-root', required=True, type=Path)
    args = parser.parse_args()
    rects = build(args.review_root, args.outfit_root, args.outfit_id)
    for frame_name, source_rect in rects.items():
        print(frame_name, *source_rect)


if __name__ == '__main__':
    main()
