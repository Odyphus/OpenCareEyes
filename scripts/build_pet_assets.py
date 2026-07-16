'''Split a generated 4x4 pet pose sheet into clean, deterministic PNG frames.'''

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter


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
    build_accessories(output.parent / 'accessories', size)


def build_accessories(output: Path, size: int) -> None:
    '''Create anatomy-neutral full-canvas overlays for semantic appearance slots.'''

    output.mkdir(parents=True, exist_ok=True)

    def canvas() -> tuple[Image.Image, ImageDraw.ImageDraw]:
        image = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        return image, ImageDraw.Draw(image)

    image, draw = canvas()
    draw.rounded_rectangle((64, 66, 119, 91), 10, fill=(22, 28, 42, 238))
    draw.rounded_rectangle((137, 66, 192, 91), 10, fill=(22, 28, 42, 238))
    draw.line((119, 76, 137, 76), fill=(22, 28, 42, 238), width=7)
    draw.line((78, 70, 105, 70), fill=(114, 202, 255, 155), width=4)
    draw.line((151, 70, 178, 70), fill=(114, 202, 255, 155), width=4)
    image.save(output / 'sunglasses.png', optimize=True)

    image, draw = canvas()
    draw.polygon(
        ((68, 119), (96, 102), (160, 102), (190, 121), (178, 214), (79, 214)),
        fill=(255, 198, 55, 218),
        outline=(220, 151, 27, 245),
    )
    draw.line((128, 112, 128, 205), fill=(244, 164, 28, 245), width=4)
    draw.ellipse((119, 127, 137, 145), fill=(90, 163, 217, 240))
    image.save(output / 'raincoat.png', optimize=True)

    image, draw = canvas()
    draw.arc((145, 38, 247, 142), 185, 355, fill=(82, 139, 215, 250), width=14)
    draw.line((196, 92, 196, 217), fill=(91, 76, 67, 245), width=7)
    draw.arc((179, 195, 210, 230), 0, 170, fill=(91, 76, 67, 245), width=7)
    image.save(output / 'umbrella.png', optimize=True)

    image, draw = canvas()
    draw.rounded_rectangle((77, 97, 179, 124), 12, fill=(90, 164, 228, 235))
    draw.polygon(((149, 118), (177, 173), (153, 180), (127, 120)), fill=(63, 136, 205, 235))
    image.save(output / 'scarf.png', optimize=True)

    image, draw = canvas()
    draw.rounded_rectangle((77, 97, 179, 124), 12, fill=(210, 54, 67, 240))
    draw.polygon(((149, 118), (177, 173), (153, 180), (127, 120)), fill=(184, 38, 54, 240))
    image.save(output / 'red_scarf.png', optimize=True)

    image, draw = canvas()
    for x, y, radius in (
        (28, 49, 4), (67, 28, 3), (216, 53, 4), (229, 125, 3),
        (43, 154, 3), (202, 191, 4), (111, 24, 3), (22, 213, 3),
    ):
        draw.line((x - radius, y, x + radius, y), fill=(219, 241, 255, 220), width=2)
        draw.line((x, y - radius, x, y + radius), fill=(219, 241, 255, 220), width=2)
    image.save(output / 'snow_effect.png', optimize=True)

    image, draw = canvas()
    draw.polygon(((38, 67), (8, 153), (68, 153)), fill=(43, 143, 88, 235))
    draw.polygon(((38, 94), (3, 184), (73, 184)), fill=(36, 124, 76, 240))
    draw.rectangle((32, 181, 44, 218), fill=(111, 74, 44, 245))
    for point in ((23, 132), (50, 149), (31, 171), (57, 177)):
        draw.ellipse((point[0] - 4, point[1] - 4, point[0] + 4, point[1] + 4), fill=(244, 69, 70, 245))
    image.save(output / 'christmas_tree.png', optimize=True)

    image, draw = canvas()
    draw.rounded_rectangle((181, 115, 237, 186), 16, fill=(227, 55, 65, 235), outline=(255, 189, 71, 255), width=4)
    draw.line((190, 112, 228, 112), fill=(255, 189, 71, 255), width=4)
    draw.line((209, 93, 209, 115), fill=(255, 189, 71, 255), width=4)
    draw.line((209, 186, 209, 215), fill=(255, 189, 71, 255), width=4)
    image.save(output / 'lantern.png', optimize=True)

    image, draw = canvas()
    draw.polygon(((168, 186), (230, 124), (241, 135), (179, 197)), fill=(245, 192, 52, 245))
    draw.polygon(((230, 124), (244, 120), (241, 135)), fill=(62, 69, 83, 245))
    draw.rounded_rectangle((28, 199, 139, 213), 5, fill=(92, 158, 217, 220))
    image.save(output / 'pencil_ruler.png', optimize=True)

    image, draw = canvas()
    draw.rounded_rectangle((175, 140, 239, 218), 8, fill=(61, 74, 96, 238), outline=(143, 174, 214, 245), width=3)
    draw.rectangle((184, 150, 230, 169), fill=(182, 226, 211, 245))
    for row in range(3):
        for column in range(3):
            x, y = 185 + column * 15, 178 + row * 13
            draw.rounded_rectangle((x, y, x + 9, y + 8), 2, fill=(210, 220, 237, 245))
    image.save(output / 'calculator.png', optimize=True)

    image, draw = canvas()
    draw.rounded_rectangle((164, 137, 242, 215), 8, fill=(45, 138, 96, 238), outline=(126, 221, 171, 245), width=3)
    draw.line((175, 154, 221, 154, 221, 186, 235, 186), fill=(235, 201, 91, 245), width=3)
    draw.line((178, 202, 198, 202, 198, 170, 229, 170), fill=(235, 201, 91, 245), width=3)
    for x, y in ((175, 154), (221, 186), (198, 170), (229, 170)):
        draw.ellipse((x - 4, y - 4, x + 4, y + 4), fill=(211, 227, 235, 245))
    image.save(output / 'pcb.png', optimize=True)

    image, draw = canvas()
    draw.ellipse((176, 156, 234, 214), fill=(222, 91, 142, 245), outline=(151, 54, 102, 255), width=4)
    draw.arc((182, 163, 225, 206), 18, 195, fill=(255, 181, 214, 245), width=4)
    draw.arc((184, 170, 228, 210), 205, 355, fill=(132, 48, 92, 245), width=4)
    draw.line((179, 189, 155, 207), fill=(222, 91, 142, 235), width=3)
    image.save(output / 'yarn_ball.png', optimize=True)

    image, draw = canvas()
    draw.rounded_rectangle((176, 158, 231, 211), 9, fill=(217, 238, 245, 245), outline=(91, 133, 151, 255), width=4)
    draw.arc((222, 169, 249, 199), 270, 90, fill=(91, 133, 151, 255), width=5)
    draw.ellipse((183, 164, 224, 178), fill=(116, 67, 43, 250))
    draw.arc((187, 142, 204, 166), 70, 250, fill=(239, 246, 250, 180), width=3)
    draw.arc((207, 139, 224, 165), 70, 250, fill=(239, 246, 250, 180), width=3)
    image.save(output / 'hot_cocoa.png', optimize=True)

    image, draw = canvas()
    draw.ellipse((181, 151, 230, 216), fill=(122, 77, 43, 245), outline=(78, 46, 27, 255), width=4)
    for y in range(162, 207, 13):
        draw.arc((184, y, 227, y + 18), 10, 170, fill=(204, 141, 78, 245), width=4)
        draw.arc((184, y - 5, 227, y + 13), 190, 350, fill=(92, 54, 31, 245), width=3)
    image.save(output / 'pine_cone.png', optimize=True)


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
