"""Offline alpha matting for pose sheets rendered on a magenta key."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image


BORDER_SAMPLE = 32
SURE_BACKGROUND_ALPHA = 0.06
TRUSTED_FOREGROUND_ALPHA = 0.85
BACKGROUND_GROW_STEPS = 4
FOREGROUND_GROW_STEPS = 6
MIN_VISIBLE_ALPHA = 0.012
LINE_RESIDUAL_LIMIT = 0.07


def _neighbour_any(mask: np.ndarray) -> np.ndarray:
    padded = np.pad(mask, 1)
    height, width = mask.shape
    result = np.zeros_like(mask)
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
        result |= padded[
            1 + delta_y : 1 + delta_y + height,
            1 + delta_x : 1 + delta_x + width,
        ]
    return result


def _estimate_key_colour(rgb: np.ndarray) -> np.ndarray:
    border = min(BORDER_SAMPLE, rgb.shape[0] // 4, rgb.shape[1] // 4)
    if border <= 0:
        raise ValueError("image is too small to estimate its key colour")
    samples = np.concatenate(
        (
            rgb[:border].reshape(-1, 3),
            rgb[-border:].reshape(-1, 3),
            rgb[:, :border].reshape(-1, 3),
            rgb[:, -border:].reshape(-1, 3),
        )
    )
    return np.median(samples, axis=0)


def _propagate_foreground(
    rgb: np.ndarray,
    trusted_foreground: np.ndarray,
    target: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Propagate nearby trusted colours into the narrow antialiasing band."""

    height, width, _channels = rgb.shape
    colours = rgb.copy()
    assigned = trusted_foreground.copy()

    for _step in range(FOREGROUND_GROW_STEPS):
        newly_assigned = target & ~assigned & _neighbour_any(assigned)
        if not newly_assigned.any():
            break

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

        colours[newly_assigned] = colour_sum[newly_assigned] / np.maximum(
            neighbour_count[newly_assigned, None],
            1.0,
        )
        assigned[newly_assigned] = True

    return colours, assigned


def _matte_cell(source: Image.Image) -> Image.Image:
    """Solve a topology-aware local colour-line matte for one keyed image."""

    source_rgba = np.asarray(source.convert("RGBA"), dtype=np.float32) / 255.0
    rgb = source_rgba[..., :3]
    source_alpha = source_rgba[..., 3]
    height, width, _channels = rgb.shape
    key_colour = _estimate_key_colour(rgb)
    key_strength = float(
        min(key_colour[0], key_colour[2]) - key_colour[1]
    )
    if key_strength < 0.2:
        raise ValueError(
            "canvas border is not a sufficiently saturated magenta key"
        )

    magenta_excess = np.minimum(rgb[..., 0], rgb[..., 2]) - rgb[..., 1]
    initial_alpha = np.clip(
        1.0 - magenta_excess / key_strength,
        0.0,
        1.0,
    )

    sure_background = initial_alpha <= SURE_BACKGROUND_ALPHA
    passable = initial_alpha < TRUSTED_FOREGROUND_ALPHA
    background_reachable = sure_background.copy()
    for _step in range(BACKGROUND_GROW_STEPS):
        background_reachable |= (
            _neighbour_any(background_reachable) & passable
        )

    trusted_foreground = ~background_reachable
    local_foreground, foreground_reachable = _propagate_foreground(
        rgb,
        trusted_foreground,
        background_reachable & (initial_alpha > 0.002),
    )
    unknown_band = background_reachable & foreground_reachable

    colour_line = local_foreground - key_colour
    denominator = np.sum(colour_line * colour_line, axis=2)
    line_alpha = np.clip(
        np.sum((rgb - key_colour) * colour_line, axis=2)
        / np.maximum(denominator, 1e-6),
        0.0,
        1.0,
    )
    reconstructed_composite = (
        key_colour + line_alpha[..., None] * colour_line
    )
    line_residual = np.sqrt(
        np.mean((reconstructed_composite - rgb) ** 2, axis=2)
    )

    alpha = np.zeros((height, width), dtype=np.float32)
    alpha[trusted_foreground] = 1.0
    solved_alpha = np.where(
        line_residual < LINE_RESIDUAL_LIMIT,
        line_alpha,
        initial_alpha,
    )
    alpha[unknown_band] = solved_alpha[unknown_band]
    alpha *= source_alpha
    alpha[alpha < MIN_VISIBLE_ALPHA] = 0.0

    recovered = np.clip(
        (rgb - (1.0 - alpha[..., None]) * key_colour)
        / np.maximum(alpha, 0.03)[..., None],
        0.0,
        1.0,
    )
    recovered_weight = np.clip(
        (alpha - 0.08) / 0.52,
        0.0,
        1.0,
    )[..., None]
    foreground = (
        local_foreground * (1.0 - recovered_weight)
        + recovered * recovered_weight
    )

    visible = alpha >= (16.0 / 255.0)
    obvious_spill = (
        visible
        & (foreground[..., 0] >= (180.0 / 255.0))
        & (foreground[..., 2] >= (140.0 / 255.0))
        & (foreground[..., 1] <= (90.0 / 255.0))
    )
    edge_spill = (
        visible
        & (alpha < 0.98)
        & (foreground[..., 0] >= 0.65)
        & (foreground[..., 2] >= 0.45)
        & (
            np.minimum(foreground[..., 0], foreground[..., 2])
            - foreground[..., 1]
            > 0.005
        )
    )
    residual_spill = obvious_spill | edge_spill
    neutral_green = np.minimum(
        foreground[..., 0],
        foreground[..., 2],
    )
    foreground[..., 1][residual_spill] = np.maximum(
        foreground[..., 1][residual_spill],
        neutral_green[residual_spill],
    )
    foreground[alpha <= 0.0] = 0.0

    rgba = np.empty((height, width, 4), dtype=np.uint8)
    rgba[..., :3] = np.round(
        np.clip(foreground, 0.0, 1.0) * 255
    ).astype(np.uint8)
    rgba[..., 3] = np.round(alpha * 255).astype(np.uint8)
    return Image.fromarray(rgba, "RGBA")


def quality_report(result: Image.Image) -> dict[str, int]:
    rgba = np.asarray(result.convert("RGBA"), dtype=np.uint8)
    alpha = rgba[..., 3]
    visible_spill = (
        (alpha >= 16)
        & (rgba[..., 0] >= 180)
        & (rgba[..., 2] >= 140)
        & (rgba[..., 1] <= 90)
    )
    border_alpha = np.concatenate(
        (
            alpha[:16].ravel(),
            alpha[-16:].ravel(),
            alpha[:, :16].ravel(),
            alpha[:, -16:].ravel(),
        )
    )
    return {
        "visible_magenta_spill_pixels": int(visible_spill.sum()),
        "border_alpha_max": int(border_alpha.max(initial=0)),
        "partial_alpha_pixels": int(
            ((alpha > 4) & (alpha < 251)).sum()
        ),
    }


def refine_sheet(
    source: Path,
    output: Path,
    *,
    columns: int,
    rows: int,
) -> dict[str, int]:
    if columns <= 0 or rows <= 0:
        raise ValueError("columns and rows must be positive")
    with Image.open(source) as opened:
        result = _matte_cell(opened)
    output.parent.mkdir(parents=True, exist_ok=True)
    result.save(output, optimize=True)
    return quality_report(result)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--columns", required=True, type=int)
    parser.add_argument("--rows", required=True, type=int)
    args = parser.parse_args()
    metrics = refine_sheet(
        args.input,
        args.out,
        columns=args.columns,
        rows=args.rows,
    )
    for name, value in metrics.items():
        print(f"{name}: {value}")


if __name__ == "__main__":
    main()
