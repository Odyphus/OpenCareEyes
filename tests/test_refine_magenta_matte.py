from __future__ import annotations

from PIL import Image

from scripts.refine_magenta_matte import _matte_cell


def _composite(
    foreground: tuple[int, int, int],
    background: tuple[int, int, int],
    alpha: float,
) -> tuple[int, int, int, int]:
    return (
        *(
            round(alpha * value + (1.0 - alpha) * key)
            for value, key in zip(foreground, background)
        ),
        255,
    )


def test_local_matte_reconstructs_white_fur_without_magenta_spill():
    key = (241, 7, 212)
    image = Image.new('RGBA', (24, 24), (*key, 255))
    for x in range(8, 16):
        for y in range(8, 16):
            image.putpixel((x, y), _composite((252, 250, 246), key, 0.5))
    for x in range(10, 14):
        for y in range(10, 14):
            image.putpixel((x, y), (252, 250, 246, 255))

    result = _matte_cell(image)
    red, green, blue, alpha = result.getpixel((8, 10))

    assert 90 <= alpha <= 165
    assert max(red, green, blue) - min(red, green, blue) <= 20
    assert result.getpixel((0, 0))[3] == 0


def test_local_matte_reconstructs_a_wide_watercolor_fur_edge():
    key = (241, 7, 212)
    fur = (252, 250, 246)
    image = Image.new('RGBA', (48, 48), (*key, 255))
    for inset, alpha in enumerate((0.08, 0.16, 0.28, 0.42, 0.58, 0.72, 0.84)):
        for x in range(8 + inset, 40 - inset):
            for y in range(8 + inset, 40 - inset):
                image.putpixel((x, y), _composite(fur, key, alpha))
    for x in range(16, 32):
        for y in range(16, 32):
            image.putpixel((x, y), (*fur, 255))

    result = _matte_cell(image)
    red, green, blue, alpha = result.getpixel((12, 24))

    assert 80 <= alpha <= 210
    assert max(red, green, blue) - min(red, green, blue) <= 24
    assert result.getpixel((0, 0))[3] == 0


def test_local_matte_preserves_opaque_red_prop_and_pink_ear():
    key = (241, 7, 212)
    image = Image.new('RGBA', (24, 24), (*key, 255))
    image.putpixel((10, 10), (238, 61, 68, 255))
    image.putpixel((11, 10), (244, 162, 184, 255))

    result = _matte_cell(image)

    assert result.getpixel((10, 10)) == (238, 61, 68, 255)
    assert result.getpixel((11, 10)) == (244, 162, 184, 255)


def test_local_matte_never_increases_original_alpha():
    key = (241, 7, 212)
    image = Image.new('RGBA', (24, 24), (*key, 255))
    image.putpixel((10, 10), (250, 248, 244, 96))
    image.putpixel((11, 10), (0, 0, 0, 0))

    result = _matte_cell(image)

    assert result.getpixel((10, 10))[3] <= 96
    assert result.getpixel((11, 10))[3] == 0
