from scripts.sync_official_outfits import ACTION_LAYOUT, outfit_definition


def test_standard_outfit_manifest_has_ten_actions_and_29_frames():
    outfit = outfit_definition(
        {
            'outfit_id': 'round_shades',
            'display_name': '圆镜酷鼬',
            'description': '黑色圆镜造型。',
        }
    )

    assert set(outfit['actions']) == set(ACTION_LAYOUT)
    assert sum(
        len(action['frames']) for action in outfit['actions'].values()
    ) == 29
    assert outfit['actions']['move']['loop'] is True
    assert outfit['actions']['drag_hold']['loop'] is True
    assert outfit['actions']['click_reaction'].get('loop') is None
    for action in outfit['actions'].values():
        for frame in action['frames']:
            left, top, width, height = frame['source_rect']
            assert width == height == 384
            assert 0 <= left <= 1152
            assert 0 <= top <= 1152
