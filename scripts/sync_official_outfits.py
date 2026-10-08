'''Synchronise completed official outfits into the snow-ferret manifest.'''

from __future__ import annotations

import argparse
import json
from pathlib import Path


CELL_SIZE = 384
GRID_SIZE = 4

# action_id: (atlas, start cell, durations, loop)
ACTION_LAYOUT = {
    'idle': (1, 0, (900, 180, 1100), True),
    'sleep': (1, 3, (1250, 1250), True),
    'move': (1, 5, (180, 180, 180, 180), True),
    'click_reaction': (1, 9, (160, 160, 300), False),
    'drag_hold': (1, 12, (500,), True),
    'drag_release': (1, 13, (180, 240, 520), False),
    'right_click_reaction': (2, 0, (260, 720, 260), False),
    'rest_prompt': (2, 3, (480, 620, 760), True),
    'play': (2, 6, (180, 220, 260, 320), False),
    'look_cursor': (2, 10, (600, 600, 600), False),
}


def _source_rect(index: int) -> list[int]:
    row, column = divmod(index, GRID_SIZE)
    return [
        column * CELL_SIZE,
        row * CELL_SIZE,
        CELL_SIZE,
        CELL_SIZE,
    ]


def outfit_definition(entry: dict) -> dict:
    outfit_id = entry['outfit_id']
    actions = {}
    for action_id, (atlas, start, durations, loop) in ACTION_LAYOUT.items():
        action = {
            'frames': [
                {
                    'path': (
                        f'outfits/{outfit_id}/'
                        f'{outfit_id}_atlas_{atlas}.png'
                    ),
                    'duration_ms': duration,
                    'source_rect': _source_rect(start + offset),
                }
                for offset, duration in enumerate(durations)
            ]
        }
        if loop:
            action['loop'] = True
        actions[action_id] = action
    return {
        'display_name': entry['display_name'],
        'description': entry['description'],
        'thumbnail_path': f'outfits/{outfit_id}/thumbnail.png',
        'preview_path': f'outfits/{outfit_id}/preview.png',
        'actions': actions,
        'ambient_layers': {},
    }


def completed_outfits(project_root: Path) -> dict:
    catalog_path = project_root / 'docs' / 'design' / 'outfits' / 'catalog.json'
    catalog = json.loads(catalog_path.read_text(encoding='utf-8'))
    pet_root = project_root / 'assets' / 'pets' / 'snow_ferret'
    outfits = {}
    for entry in catalog['outfits']:
        if entry.get('status') != 'complete':
            continue
        outfit_id = entry['outfit_id']
        outfit_root = pet_root / 'outfits' / outfit_id
        if entry.get('motion_manifest') == 'motion.json':
            definition = json.loads((outfit_root / 'motion.json').read_text(encoding='utf-8'))
            outfits[outfit_id] = definition
            continue
        required = (
            outfit_root / f'{outfit_id}_atlas_1.png',
            outfit_root / f'{outfit_id}_atlas_2.png',
            outfit_root / 'thumbnail.png',
            outfit_root / 'preview.png',
        )
        missing = [path for path in required if not path.is_file()]
        if missing:
            raise FileNotFoundError(
                f'completed outfit {outfit_id} is missing {missing[0]}'
            )
        outfits[outfit_id] = outfit_definition(entry)
    return outfits


def sync(project_root: Path, *, check: bool = False) -> bool:
    manifest_path = (
        project_root / 'assets' / 'pets' / 'snow_ferret' / 'manifest.json'
    )
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    expected = completed_outfits(project_root)
    if manifest.get('outfits') == expected:
        return False
    if check:
        raise ValueError('official outfit manifest is not synchronised')
    manifest['outfits'] = expected
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8',
    )
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    project_root = Path(__file__).resolve().parents[1]
    sync(project_root, check=args.check)


if __name__ == '__main__':
    main()
