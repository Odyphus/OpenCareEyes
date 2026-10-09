import json
from pathlib import Path

from PIL import Image

from opencareyes.application.pet_pack_registry import PetPackRegistry
from opencareyes.constants import APP_VERSION, PETS_DIR
from scripts.sync_official_outfits import ACTION_LAYOUT


ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / 'docs' / 'design' / 'outfits' / 'catalog.json'
REFERENCE_ROOT = CATALOG_PATH.parent / 'references'
PET_ROOT = ROOT / 'assets' / 'pets' / 'snow_ferret'
MANIFEST_PATH = PET_ROOT / 'manifest.json'

EXPECTED_OUTFITS = {
    'snow_slope_skier',
    'lulu_little_ferret',
    'caramel_pastry_chef',
    'thunder_mage',
    'silverfrost_swordsman',
    'forest_detective',
    'christmas_ferret',
    'icecream_vendor',
    'beach_vacation',
    'navy_scarf',
    'blue_scarf_sprint',
    'round_shades',
    'star_shades',
}


def test_official_catalog_tracks_all_thirteen_outfits_and_sources():
    catalog = json.loads(CATALOG_PATH.read_text(encoding='utf-8'))
    entries = {entry['outfit_id']: entry for entry in catalog['outfits']}

    assert set(entries) == EXPECTED_OUTFITS
    for entry in entries.values():
        assert (REFERENCE_ROOT / entry['source']).is_file()
        action_reference = entry.get('action_reference')
        if action_reference:
            assert (REFERENCE_ROOT / action_reference).is_file()


def test_completed_catalog_entries_match_the_production_manifest():
    catalog = json.loads(CATALOG_PATH.read_text(encoding='utf-8'))
    completed = {
        entry['outfit_id']
        for entry in catalog['outfits']
        if entry['status'] == 'complete'
    }
    manifest = PetPackRegistry(PETS_DIR, app_version=APP_VERSION).load(
        'snow_ferret'
    )

    assert set(manifest.outfits) == completed
    for outfit in manifest.outfits.values():
        expected_actions = set(ACTION_LAYOUT)
        if outfit.outfit_id == 'navy_scarf':
            expected_actions.update({'yawn', 'look_grid'})
            expected_actions.update(f'look_{direction}' for direction in (
                'center', 'left', 'right', 'up', 'down',
                'up_left', 'up_right', 'down_left', 'down_right',
            ))
        assert set(outfit.actions) == expected_actions
        expected_frames = 143 if outfit.outfit_id == 'navy_scarf' else 29
        assert sum(len(action.frames) for action in outfit.actions.values()) == expected_frames


def test_official_pet_pack_stays_inside_the_64_mib_budget():
    assert sum(
        path.stat().st_size for path in PET_ROOT.rglob('*') if path.is_file()
    ) <= 64 * 1024 * 1024


def _frame_alpha_metrics(frame):
    with Image.open(PET_ROOT / frame['path']) as atlas:
        x, y, width, height = frame['source_rect']
        alpha = atlas.convert('RGBA').crop(
            (x, y, x + width, y + height)
        ).getchannel('A')
    bbox = alpha.getbbox()
    assert bbox is not None
    return (
        bbox[2] - bbox[0],
        bbox[3] - bbox[1],
        sum(alpha.histogram()[9:]),
    )


def test_thunder_mage_interactions_keep_the_idle_character_scale():
    manifest = json.loads(MANIFEST_PATH.read_text(encoding='utf-8'))
    actions = manifest['outfits']['thunder_mage']['actions']
    idle_metrics = [_frame_alpha_metrics(frame) for frame in actions['idle']['frames']]
    idle_height = sorted(metric[1] for metric in idle_metrics)[1]
    idle_area = sorted(metric[2] for metric in idle_metrics)[1]

    click_metrics = [
        _frame_alpha_metrics(frame)
        for frame in actions['click_reaction']['frames']
    ]
    assert min(metric[1] / idle_height for metric in click_metrics) >= 0.85
    assert min(metric[2] / idle_area for metric in click_metrics) >= 0.80

    hold_metric = _frame_alpha_metrics(actions['drag_hold']['frames'][0])
    assert hold_metric[1] / idle_height >= 1.0
    assert hold_metric[2] / idle_area >= 0.50

    release_metrics = [
        _frame_alpha_metrics(frame)
        for frame in actions['drag_release']['frames']
    ]
    assert min(metric[1] / idle_height for metric in release_metrics) >= 0.84
    assert min(metric[2] / idle_area for metric in release_metrics) >= 0.75
