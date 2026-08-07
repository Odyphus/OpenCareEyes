from pathlib import Path

from PIL import Image, ImageDraw

from scripts.build_pet_outfit import FRAME_SOURCES, build


def _sheet(path: Path, columns: int, rows: int) -> None:
    image = Image.new('RGBA', (columns * 120, rows * 140), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    for index in range(columns * rows):
        row, column = divmod(index, columns)
        left = column * 120 + 20
        top = row * 140 + 20
        draw.ellipse(
            (left, top, left + 70, top + 90),
            fill=(30 + index * 7, 80, 180, 255),
        )
    image.save(path)


def _uneven_sheet(path: Path, columns: int, rows: int) -> None:
    image = Image.new('RGBA', (columns * 123 + 17, rows * 137 + 11), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    for index in range(columns * rows):
        row, column = divmod(index, columns)
        left = round((column + 0.16) * image.width / columns)
        top = round((row + 0.13) * image.height / rows)
        width = 63 + (index % 3) * 6
        height = 81 + (index % 2) * 8
        draw.rounded_rectangle(
            (left, top, left + width, top + height),
            radius=12,
            fill=(50 + index * 5, 90, 190, 255),
        )
    image.save(path)


def _sheet_with_neighbor_fragment(path: Path, columns: int, rows: int) -> None:
    _sheet(path, columns, rows)
    with Image.open(path) as source:
        image = source.convert('RGBA')
    draw = ImageDraw.Draw(image)
    # The character, tail, and sword are one connected subject.
    draw.ellipse((25, 20, 85, 125), fill=(30, 80, 180, 255))
    draw.polygon(
        ((30, 85), (2, 95), (10, 122), (38, 110)),
        fill=(20, 180, 80, 255),
    )
    draw.line((62, 35, 96, 3), fill=(20, 180, 80, 255), width=6)
    # A sizeable detached prop near the edge remains meaningful.
    draw.rounded_rectangle(
        (92, 48, 110, 85),
        radius=4,
        fill=(240, 190, 20, 255),
    )
    # A thin fragment from the adjacent pose must not enter idle_1.
    draw.rectangle((115, 50, 118, 85), fill=(220, 20, 40, 255))
    image.save(path)


def test_builds_standard_29_frame_outfit(tmp_path):
    review = tmp_path / 'review'
    output = tmp_path / 'outfit'
    review.mkdir()
    _sheet(review / 'sheet_idle_sleep_rgba.png', 4, 2)
    _sheet(review / 'sheet_move_play_rgba.png', 4, 2)
    _sheet(review / 'sheet_click_drag_rgba.png', 4, 2)
    _sheet(review / 'sheet_shy_rest_rgba.png', 3, 2)

    rects = build(review, output, 'test_outfit')

    assert len(rects) == len(FRAME_SOURCES) == 29
    assert set(rects) == {source.name for source in FRAME_SOURCES}
    for atlas_number in (1, 2):
        with Image.open(output / f'test_outfit_atlas_{atlas_number}.png') as atlas:
            assert atlas.mode == 'RGBA'
            assert atlas.size == (1536, 1536)
    with Image.open(output / 'thumbnail.png') as thumbnail:
        assert thumbnail.mode == 'RGBA'
        assert thumbnail.size == (256, 256)
        assert thumbnail.getchannel('A').getbbox() is not None
    with Image.open(output / 'preview.png') as preview:
        assert preview.mode == 'RGBA'
        assert preview.size == (512, 512)


def test_adapts_to_uneven_generated_sheet_gutters(tmp_path):
    review = tmp_path / 'review'
    output = tmp_path / 'outfit'
    review.mkdir()
    _uneven_sheet(review / 'sheet_idle_sleep_rgba.png', 4, 2)
    _uneven_sheet(review / 'sheet_move_play_rgba.png', 4, 2)
    _uneven_sheet(review / 'sheet_click_drag_rgba.png', 4, 2)
    _uneven_sheet(review / 'sheet_shy_rest_rgba.png', 3, 2)

    rects = build(review, output, 'uneven')

    assert len(rects) == 29
    with Image.open(output / 'uneven_atlas_1.png') as atlas:
        for index in range(16):
            row, column = divmod(index, 4)
            cell = atlas.crop(
                (
                    column * 384,
                    row * 384,
                    (column + 1) * 384,
                    (row + 1) * 384,
                )
            )
            assert cell.getchannel('A').getbbox() is not None


def test_removes_small_detached_neighbor_fragment_without_losing_subject_or_prop(
    tmp_path,
):
    review = tmp_path / 'review'
    output = tmp_path / 'outfit'
    review.mkdir()
    _sheet_with_neighbor_fragment(
        review / 'sheet_idle_sleep_rgba.png',
        4,
        2,
    )
    _sheet(review / 'sheet_move_play_rgba.png', 4, 2)
    _sheet(review / 'sheet_click_drag_rgba.png', 4, 2)
    _sheet(review / 'sheet_shy_rest_rgba.png', 3, 2)

    build(review, output, 'fragment')

    with Image.open(output / 'preview.png') as preview:
        colors = preview.convert('RGBA').get_flattened_data()
        assert any(g > 140 and r < 80 for r, g, _b, a in colors if a)
        assert any(r > 180 and g > 140 for r, g, _b, a in colors if a)
        assert not any(r > 160 and g < 80 for r, g, _b, a in colors if a)
