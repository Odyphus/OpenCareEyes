'''Remove residual chroma colour from the narrow alpha edge of outfit sheets.'''

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image


def _erode(mask: np.ndarray, radius: int) -> np.ndarray:
    result = mask.copy()
    padded = np.pad(mask, radius, constant_values=False)
    height, width = mask.shape
    for delta_y in range(-radius, radius + 1):
        for delta_x in range(-radius, radius + 1):
            result &= padded[
                radius + delta_y : radius + delta_y + height,
                radius + delta_x : radius + delta_x + width,
            ]
    return result


def _propagate_neighbour_colours(
    rgb: np.ndarray,
    trusted: np.ndarray,
    target: np.ndarray,
    *,
    steps: int = 12,
) -> tuple[np.ndarray, np.ndarray]:
    colours = rgb.astype(np.float32).copy()
    assigned = trusted.copy()
    height, width = trusted.shape
    for _step in range(steps):
        padded_colours = np.pad(colours, ((1, 1), (1, 1), (0, 0)))
        padded_assigned = np.pad(assigned, 1)
        colour_sum = np.zeros_like(colours)
        neighbour_count = np.zeros((height, width), dtype=np.float32)
        for delta_y, delta_x in (
            (-1, -1),
            (-1, 0),
            (-1, 1),
            (0, -1),
            (0, 1),
            (1, -1),
            (1, 0),
            (1, 1),
        ):
            neighbour = padded_assigned[
                1 + delta_y : 1 + delta_y + height,
                1 + delta_x : 1 + delta_x + width,
            ]
            neighbour_colours = padded_colours[
                1 + delta_y : 1 + delta_y + height,
                1 + delta_x : 1 + delta_x + width,
            ]
            colour_sum += neighbour_colours * neighbour[..., None]
            neighbour_count += neighbour
        newly_assigned = target & ~assigned & (neighbour_count > 0)
        if not newly_assigned.any():
            break
        colours[newly_assigned] = (
            colour_sum[newly_assigned]
            / neighbour_count[newly_assigned, None]
        )
        assigned[newly_assigned] = True
    return colours, assigned


def clean_edges(image: Image.Image, key: str) -> Image.Image:
    rgba = np.asarray(image.convert('RGBA'), dtype=np.uint8).copy()
    alpha = rgba[..., 3]
    visible = alpha >= 4
    # Generated watercolor strokes can leave an opaque keyed outline several
    # pixels inside the alpha contour.  Inspect a wider contour band while
    # keeping interior clothing colours untouched.
    edge = visible & ~_erode(visible, 8)
    edge |= visible & (alpha < 251)

    red = rgba[..., 0].astype(np.int16)
    green = rgba[..., 1].astype(np.int16)
    blue = rgba[..., 2].astype(np.int16)
    if key == 'magenta':
        neutral = np.minimum(red, blue)
        excess = neutral - green
        spill = (
            edge
            & (alpha < 251)
            & (excess > 4)
            & (red > 110)
            & (blue > 75)
        )
        strong_spill = (
            edge
            & (excess > 10)
            & ((green < 100) | (np.abs(red - blue) < 35))
            & (red > 45)
            & (blue > 45)
            & (blue * 100 > red * 40)
            & (red * 100 > blue * 40)
        )
        extreme = (
            edge
            & (red > 205)
            & (blue > 175)
            & (green < 90)
            & (excess > 100)
        )
        rgba[..., 1][spill] = np.maximum(
            rgba[..., 1][spill],
            neutral[spill].astype(np.uint8),
        )
        propagated, assigned = _propagate_neighbour_colours(
            rgba[..., :3],
            visible & ~strong_spill,
            strong_spill,
        )
        propagated = np.clip(np.rint(propagated), 0, 255).astype(np.uint8)
        rgba[..., :3][strong_spill & assigned] = propagated[
            strong_spill & assigned
        ]
        unresolved = strong_spill & ~assigned
        luminance = np.clip(
            np.rint(0.299 * red + 0.587 * green + 0.114 * blue),
            0,
            255,
        ).astype(np.uint8)
        for channel in range(3):
            rgba[..., channel][unresolved] = luminance[unresolved]
        post_red = rgba[..., 0].astype(np.int16)
        post_green = rgba[..., 1].astype(np.int16)
        post_blue = rgba[..., 2].astype(np.int16)
        residual = (
            strong_spill
            & (post_green < 100)
            & (np.minimum(post_red, post_blue) - post_green > 8)
        )
        residual_luminance = np.clip(
            np.rint(
                0.299 * post_red
                + 0.587 * post_green
                + 0.114 * post_blue
            ),
            0,
            255,
        ).astype(np.uint8)
        for channel in range(3):
            rgba[..., channel][residual] = residual_luminance[residual]
    elif key == 'green':
        neutral = np.maximum(red, blue)
        excess = green - neutral
        spill = edge & (excess > 4) & (green > 110)
        extreme = (
            edge
            & (green > 205)
            & (red < 90)
            & (blue < 90)
            & (excess > 100)
        )
        replacement = ((red + blue) // 2).astype(np.uint8)
        rgba[..., 1][spill] = np.minimum(
            rgba[..., 1][spill],
            replacement[spill],
        )
    else:
        raise ValueError('key must be magenta or green')

    rgba[..., 3][extreme | (rgba[..., 3] < 12)] = 0
    rgba[rgba[..., 3] == 0, :3] = 0
    return Image.fromarray(rgba, 'RGBA')


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--key', choices=('magenta', 'green'), required=True)
    args = parser.parse_args()
    with Image.open(args.input) as opened:
        result = clean_edges(opened, args.key)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    result.save(args.out, optimize=True)


if __name__ == '__main__':
    main()
