'''Split a generated 4x4 pet pose sheet into clean, deterministic PNG frames.'''

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageChops, ImageFilter


_FRAME_NAMES = (
    'idle',
    'blink',
    'head_tilt',
    'yawn',
    'walk_1',
    'walk_2',
    'edge_paw',
    'jump',
    'roll',
    'tail_chase',
    'sleep',
    'cursor_paw',
    'drag_hold',
    'stumble',
    'shy_back',
    'rest_prompt',
)


@dataclass(frozen=True)
class _Component:
    pixels: tuple[int, ...]
    bbox: tuple[int, int, int, int]
    center: tuple[float, float]


def _connected_components(alpha: Image.Image, threshold: int) -> list[_Component]:
    '''Return 8-connected alpha components without assuming divisible grid cells.'''

    width, height = alpha.size
    foreground = bytearray(value >= threshold for value in alpha.tobytes())
    seen = bytearray(width * height)
    components: list[_Component] = []

    for start, is_foreground in enumerate(foreground):
        if not is_foreground or seen[start]:
            continue
        stack = [start]
        seen[start] = 1
        pixels: list[int] = []
        min_x, min_y = width, height
        max_x = max_y = 0
        sum_x = sum_y = 0
        while stack:
            position = stack.pop()
            y, x = divmod(position, width)
            pixels.append(position)
            min_x, min_y = min(min_x, x), min(min_y, y)
            max_x, max_y = max(max_x, x), max(max_y, y)
            sum_x += x
            sum_y += y
            for neighbour_y in range(max(0, y - 1), min(height, y + 2)):
                row_start = neighbour_y * width
                for neighbour_x in range(max(0, x - 1), min(width, x + 2)):
                    neighbour = row_start + neighbour_x
                    if foreground[neighbour] and not seen[neighbour]:
                        seen[neighbour] = 1
                        stack.append(neighbour)
        count = len(pixels)
        components.append(
            _Component(
                pixels=tuple(pixels),
                bbox=(min_x, min_y, max_x + 1, max_y + 1),
                center=(sum_x / count, sum_y / count),
            )
        )
    return components


def _clean_cell(
    source: Image.Image,
    components: list[_Component],
    *,
    matte_radius: int,
) -> Image.Image:
    width, height = source.size
    left = max(0, min(component.bbox[0] for component in components) - matte_radius)
    top = max(0, min(component.bbox[1] for component in components) - matte_radius)
    right = min(width, max(component.bbox[2] for component in components) + matte_radius)
    bottom = min(height, max(component.bbox[3] for component in components) + matte_radius)
    box = (left, top, right, bottom)

    keep_mask = Image.new('L', (right - left, bottom - top), 0)
    keep_pixels = keep_mask.load()
    for component in components:
        for position in component.pixels:
            y, x = divmod(position, width)
            keep_pixels[x - left, y - top] = 255
    if matte_radius:
        keep_mask = keep_mask.filter(ImageFilter.MaxFilter(matte_radius * 2 + 1))

    cleaned = source.crop(box)
    original_alpha = cleaned.getchannel('A')
    cleaned.putalpha(ImageChops.multiply(original_alpha, keep_mask))
    content_box = cleaned.getchannel('A').getbbox()
    if content_box is None:
        raise ValueError('pet sprite component has no visible alpha')
    return cleaned.crop(content_box)


def _extract_frames(
    source: Image.Image,
    *,
    alpha_threshold: int,
    min_component_area: int,
    matte_radius: int,
) -> list[Image.Image]:
    groups: list[list[_Component]] = [[] for _ in _FRAME_NAMES]
    for component in _connected_components(source.getchannel('A'), alpha_threshold):
        if len(component.pixels) < min_component_area:
            continue
        center_x, center_y = component.center
        column = min(3, int(center_x * 4 / source.width))
        row = min(3, int(center_y * 4 / source.height))
        groups[row * 4 + column].append(component)

    missing = [name for name, components in zip(_FRAME_NAMES, groups) if not components]
    if missing:
        raise ValueError(f'pose sheet has no visible component for: {", ".join(missing)}')
    return [
        _clean_cell(source, components, matte_radius=matte_radius)
        for components in groups
    ]


def _render_frames(frames: list[Image.Image], size: int, safe_margin: int) -> list[Image.Image]:
    if size <= 0 or safe_margin < 0 or safe_margin * 2 >= size:
        raise ValueError('size and safe margin must leave a visible canvas')
    available = size - safe_margin * 2
    reference_extent = max(max(frame.size) for frame in frames)
    scale = min(1.0, available / reference_extent)
    rendered: list[Image.Image] = []
    for frame in frames:
        target = (
            max(1, round(frame.width * scale)),
            max(1, round(frame.height * scale)),
        )
        resized = frame.resize(target, Image.Resampling.LANCZOS)
        canvas = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        canvas.alpha_composite(
            resized,
            ((size - resized.width) // 2, (size - resized.height) // 2),
        )
        rendered.append(canvas)
    return rendered


def split_sheet(
    source: Path,
    output: Path,
    size: int = 256,
    *,
    safe_margin: int = 16,
    alpha_threshold: int = 16,
    min_component_area: int = 16,
    matte_radius: int = 2,
) -> None:
    image = Image.open(source).convert('RGBA')
    output.mkdir(parents=True, exist_ok=True)
    frames = _render_frames(
        _extract_frames(
            image,
            alpha_threshold=alpha_threshold,
            min_component_area=min_component_area,
            matte_radius=matte_radius,
        ),
        size,
        safe_margin,
    )
    for name, frame in zip(_FRAME_NAMES, frames):
        frame.save(output / f'{name}.png', optimize=True)
    frames[0].resize((512, 512), Image.Resampling.LANCZOS).save(
        output.parent / 'preview.png', optimize=True
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--size', type=int, default=256)
    parser.add_argument('--safe-margin', type=int, default=16)
    args = parser.parse_args()
    split_sheet(args.source, args.output, args.size, safe_margin=args.safe_margin)


if __name__ == '__main__':
    main()
