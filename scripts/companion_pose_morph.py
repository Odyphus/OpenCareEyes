"""Build-time whole-character pose interpolation; no runtime image codec.

Corresponding landmarks move on one eased path. Each frame resamples one
complete drawing to that geometry; there is no cross-fade that doubles eyes
or outlines. There are no independently cut neck, shoulder or arm layers.
"""

import numpy as np
from PIL import Image


def _warp(bitmap, source, destination):
    source = np.asarray(source, dtype=float)
    destination = np.asarray(destination, dtype=float)
    size = bitmap.width
    step = 12
    vertices = {}
    for y in range(0, size + 1, step):
        for x in range(0, size + 1, step):
            v = np.array([x, y], dtype=float)
            distances = np.sum((destination - v) ** 2, axis=1)
            near = np.argmin(distances)
            if distances[near] < 1e-8:
                mapped = source[near]
            else:
                weights = 1 / (distances + 36) ** 1.5
                total = weights.sum()
                center_d = (destination * weights[:, None]).sum(axis=0) / total
                center_s = (source * weights[:, None]).sum(axis=0) / total
                d = destination - center_d
                s = source - center_s
                denominator = np.sum(weights * np.sum(d * d, axis=1))
                a = np.sum(weights * np.sum(d * s, axis=1)) / denominator
                b = np.sum(weights * (d[:, 0] * s[:, 1] - d[:, 1] * s[:, 0])) / denominator
                r = v - center_d
                mapped = center_s + (a * r[0] - b * r[1], b * r[0] + a * r[1])
            vertices[x, y] = tuple(mapped)
    mesh = [((x, y, x + step, y + step), tuple(
        coordinate for point in ((x, y), (x, y + step), (x + step, y + step), (x + step, y))
        for coordinate in vertices[point]))
        for y in range(0, size, step) for x in range(0, size, step)]
    return bitmap.transform(bitmap.size, Image.Transform.MESH, mesh, Image.Resampling.BICUBIC)


def morph(first, second, progress, first_points, second_points):
    if progress <= 0:
        return first.copy()
    if progress >= 1:
        return second.copy()
    p = np.asarray(first_points, dtype=float)
    q = np.asarray(second_points, dtype=float)
    middle = p * (1 - progress) + q * progress
    return _warp(first, p, middle) if progress < .5 else _warp(second, q, middle)


def fixed_points():
    return [(0, 0), (192, 0), (384, 0), (0, 192), (384, 192),
            (0, 384), (192, 384), (384, 384), (192, 300),
            (147, 337), (235, 337), (305, 293)]
