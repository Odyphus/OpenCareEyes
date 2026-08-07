import numpy as np
from PIL import Image

from scripts.clean_outfit_edges import clean_edges


def test_removes_extreme_magenta_fringe_without_touching_opaque_pink():
    data = np.zeros((12, 12, 4), dtype=np.uint8)
    data[2:10, 2:10] = (245, 105, 165, 255)
    data[1, 3:9] = (255, 20, 245, 180)
    source = Image.fromarray(data, 'RGBA')

    result = np.asarray(clean_edges(source, 'magenta'))

    assert not result[1, 3:9, 3].any()
    assert tuple(result[5, 5]) == (245, 105, 165, 255)


def test_neutralises_soft_magenta_only_in_the_alpha_edge():
    data = np.zeros((12, 12, 4), dtype=np.uint8)
    data[2:10, 2:10] = (220, 120, 185, 255)
    data[2, 3:9] = (205, 110, 180, 170)
    source = Image.fromarray(data, 'RGBA')

    result = np.asarray(clean_edges(source, 'magenta'))

    expected = np.array((220, 120, 185), dtype=np.int16)
    actual = result[2, 3:9, :3].astype(np.int16)
    assert (np.abs(actual - expected) <= 15).all()
    assert (result[2, 3:9, 3] == 170).all()
    assert tuple(result[5, 5]) == (220, 120, 185, 255)


def test_neutralises_dark_opaque_key_halo_but_preserves_pink_clothing():
    data = np.zeros((32, 32, 4), dtype=np.uint8)
    data[7:25, 7:25] = (252, 250, 246, 255)
    data[6, 7:25] = (84, 6, 68, 180)
    data[25, 7:25] = (84, 6, 68, 180)
    data[7:25, 6] = (84, 6, 68, 180)
    data[7:25, 25] = (84, 6, 68, 180)
    data[12:20, 12:20] = (245, 105, 165, 255)
    source = Image.fromarray(data, 'RGBA')

    result = np.asarray(clean_edges(source, 'magenta'))

    fringe = result[6, 8:24, :3].astype(np.int16)
    assert np.max(fringe, axis=1).max() - np.min(fringe, axis=1).min() <= 8
    assert tuple(result[16, 16]) == (245, 105, 165, 255)
