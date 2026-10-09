"""Bake the 2D character into bounded, dependency-free pet atlases.

Complete artwork, joint-driven arms, shared mesh and easing are the motion source. The
desktop player keeps its existing deadline clock, cache limits and safety rules.
Run from the repository root: python -m scripts.build_companion_motion
"""

from __future__ import annotations

import json
import hashlib
import math
import os
import argparse
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PIL import Image  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication, QImage, QPainter  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PET = ROOT / 'assets/pets/snow_ferret'
CELL = 384


if __package__:
    from .companion_mesh import CoherentRig
else:
    from companion_mesh import CoherentRig


def build():
    app = QGuiApplication.instance() or QGuiApplication([])
    rig = CoherentRig()
    manifest_path = PET / 'manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    clips = {}
    idle_expressions = ['half' if i in (20, 22, 43, 45) else 'closed' if i in (21, 44)
                        else 'head' for i in range(48)]
    clips['idle'] = ([rig.frame('idle', i / 48, expression=name) for i, name in enumerate(idle_expressions)],
                     [80 if i in (20, 22, 43, 45) else 65 if i in (21, 44)
                      else 350 if i in (0, 24, 47) else 120 for i in range(48)], True)
    for action, count, duration, loop in (
        ('move', 16, 70, True), ('click_reaction', 21, 50, False),
        ('play', 29, 60, False), ('drag_hold', 12, 80, True),
        ('drag_release', 17, 50, False), ('right_click_reaction', 17, 60, False),
        ('rest_prompt', 32, 70, False), ('yawn', 23, 80, False),
        *((f'look_{direction}', 1, 600, False) for direction in rig.poses.gaze),
    ):
        beats = gesture_beats(action) if action in {'rest_prompt', 'yawn'} else [
            (index / max(1, count if loop else count - 1), duration) for index in range(count)]
        frames = [rig.frame(action, phase) for phase, _ in beats]
        clips[action] = (frames, [ms for _, ms in beats], loop)
    clips['look_grid'] = ([rig.gaze_frame(x / 2, y / 2) for y in range(-2, 3) for x in range(-2, 3)],
                          [600] * 25, False)
    clips['sleep'] = ([rig.frame('sleep')], [5000], True)
    clips['read'] = ([rig.frame('read')], [5000], True)
    clips['look_cursor'] = ([rig.frame('look_left'), rig.frame('look_center'), rig.frame('look_right')],
                            [600] * 3, False)
    for action, (frames, durations, loop) in clips.items():
        unique = {}
        slots = []
        for frame in frames:
            key = hashlib.sha256(bytes(frame.constBits())).digest()
            slots.append(unique.setdefault(key, len(unique)))
        columns = min(5, len(unique))
        rows = math.ceil(len(unique) / columns)
        atlas = QImage(columns * CELL, rows * CELL, QImage.Format_RGBA8888)
        atlas.fill(Qt.transparent)
        painter = QPainter(atlas)
        declarations = []
        painted = set()
        for index, frame in enumerate(frames):
            slot = slots[index]
            x, y = slot % columns * CELL, slot // columns * CELL
            if slot not in painted:
                painter.drawImage(x, y, frame)
                painted.add(slot)
            page, local = divmod(slot, 25)
            suffix = '' if page == 0 else f'_{page + 1}'
            declarations.append({'path': f'sprites/calm_{action}{suffix}.png',
                                 'duration_ms': durations[index],
                                 'source_rect': [local % columns * CELL,
                                                 local // columns * CELL, CELL, CELL]})
        painter.end()
        raw = Image.frombytes('RGBA', (atlas.width(), atlas.height()), bytes(atlas.constBits()))
        # One palette per whole clip keeps colour stable across all its frames.
        # Indexed PNG cuts package/decode cost without adding a runtime codec.
        indexed = raw.quantize(colors=256, method=Image.Quantize.FASTOCTREE,
                               dither=Image.Dither.NONE)
        # A page has at most 25 cells (1920² pixels), below the existing image
        # decode limit. Quantize once before paging to keep one clip palette.
        for page in range(math.ceil(len(unique) / 25)):
            suffix = '' if page == 0 else f'_{page + 1}'
            top = page * 5 * CELL
            indexed.crop((0, top, indexed.width, min(top + 5 * CELL, indexed.height))).save(
                PET / f'sprites/calm_{action}{suffix}.png', optimize=True)
        manifest['actions'][action] = {'loop': loop, 'frames': declarations}
    manifest['pack_version'] = '3.5.0'
    manifest['event_bindings']['application.focus'] = 'read'
    manifest['event_bindings']['item.play'] = 'play'
    manifest['event_bindings']['item.stretch'] = 'yawn'
    manifest['event_bindings']['item.wave'] = 'rest_prompt'
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    rig.frame().scaled(512, 512, Qt.KeepAspectRatio, Qt.SmoothTransformation).save(str(PET / 'preview.png'))
    rig.frame('sleep').save(str(PET / 'rest_sleep.png'))
    build_scarf(rig, manifest)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'Built {len(clips)} clips, {sum(len(item[0]) for item in clips.values())} registered frames.')
    return app


def build_scarf(rig, manifest):
    """Upgrade one existing outfit with the same registered rig; keep its ID."""

    outfit = manifest['outfits']['navy_scarf']
    folder = PET / 'outfits/navy_scarf'
    frames = []
    actions = {}
    for action, count, duration, loop in (
        ('idle', 11, 600, True), ('sleep', 1, 5000, True),
        ('move', 16, 70, True), ('click_reaction', 5, 200, False),
        ('drag_hold', 1, 800, True), ('drag_release', 5, 80, False),
        ('right_click_reaction', 5, 180, False), ('rest_prompt', 32, 70, False),
        ('yawn', 23, 80, False), ('look_grid', 25, 600, False),
        ('play', 7, 180, False), ('look_cursor', 3, 600, False),
        *((f'look_{direction}', 1, 600, False) for direction in rig.poses.gaze),
    ):
        declarations = []
        beats = gesture_beats(action) if action in {'rest_prompt', 'yawn'} else [
            (index / max(1, count if loop else count - 1), duration) for index in range(count)]
        for index, (phase, duration) in enumerate(beats):
            if action == 'idle':
                expression = 'half' if index in (7, 9) else 'closed' if index == 8 else 'head'
                pose = rig.frame('idle', phase, expression=expression, scarf=True)
                ms = 80 if index in (7, 9) else 65 if index == 8 else duration
            elif action == 'look_cursor':
                pose = rig.frame(['look_left', 'look_center', 'look_right'][index], 1, scarf=True)
                ms = duration
            elif action == 'look_grid':
                pose = rig.gaze_frame((index % 5 - 2) / 2, (index // 5 - 2) / 2, scarf=True)
                ms = duration
            else:
                pose = rig.frame(action, phase, scarf=True)
                ms = duration
            n = len(frames)
            atlas, cell = divmod(n, 16)
            declarations.append({'path': f'outfits/navy_scarf/motion_{atlas + 1}.png',
                                 'duration_ms': ms,
                                 'source_rect': [(cell % 4) * CELL, (cell // 4) * CELL, CELL, CELL]})
            frames.append(pose)
        actions[action] = {'loop': loop, 'frames': declarations}
    atlas = QImage(CELL * 4, math.ceil(len(frames) / 4) * CELL, QImage.Format_RGBA8888)
    atlas.fill(Qt.transparent)
    painter = QPainter(atlas)
    for cell, frame in enumerate(frames):
        painter.drawImage((cell % 4) * CELL, (cell // 4) * CELL, frame)
    painter.end()
    raw = Image.frombytes('RGBA', (atlas.width(), atlas.height()), bytes(atlas.constBits()))
    indexed = raw.quantize(colors=256, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.NONE)
    # One palette for the whole outfit prevents fur/eye colours flickering
    # when a long gesture crosses an atlas page. Runtime pages stay bounded.
    for start in range(0, len(frames), 16):
        top = start // 4 * CELL
        indexed.crop((0, top, CELL * 4, min(top + CELL * 4, indexed.height))).save(
            folder / f'motion_{start // 16 + 1}.png', optimize=True)
    outfit['actions'] = actions
    outfit['description'] = '柔软的暮蓝围巾，陪你读书，也陪你休息。自然小步走、平滑招呼、抬爪懒腰与持续鼠标注视。'
    (folder / 'motion.json').write_text(json.dumps(outfit, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    rig.frame(scarf=True).scaled(512, 512, Qt.KeepAspectRatio, Qt.SmoothTransformation).save(str(folder / 'preview.png'))
    rig.frame(scarf=True).scaled(256, 256, Qt.KeepAspectRatio, Qt.SmoothTransformation).save(str(folder / 'thumbnail.png'))


def gesture_beats(action):
    """Spend frames on movement; a held stretch needs one long-lived frame."""
    if action == 'yawn':
        return ([(0, 80)] + [(.08 + .24 * i / 10, 60) for i in range(1, 11)]
                + [(.52, 500)] + [(.72 + .24 * i / 10, 60) for i in range(1, 11)]
                + [(1, 80)])
    if action == 'rest_prompt':
        return ([(0, 50)] + [(.08 + .24 * i / 8, 60) for i in range(1, 9)]
                + [(.32 + .40 * i / 14, 70) for i in range(1, 15)]
                + [(.72 + .24 * i / 8, 60) for i in range(1, 9)] + [(1, 100)])
    raise ValueError(f'Not a gesture: {action}')


def build_gestures():
    """Replace only the two gesture cells, retaining every other outfit pixel."""
    app = QGuiApplication.instance() or QGuiApplication([])
    rig = CoherentRig()
    manifest_path = PET / 'manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    scarf_pages = {}
    for action in ('rest_prompt', 'yawn'):
        beats = gesture_beats(action)
        frames = [rig.frame(action, phase) for phase, _ in beats]
        declarations = []
        for start in range(0, len(frames), 25):
            page_frames = frames[start:start + 25]
            columns = min(5, len(page_frames))
            atlas = QImage(columns * CELL, math.ceil(len(page_frames) / columns) * CELL,
                           QImage.Format_RGBA8888)
            atlas.fill(Qt.transparent)
            painter = QPainter(atlas)
            suffix = '' if start == 0 else f'_{start // 25 + 1}'
            path = f'sprites/calm_{action}{suffix}.png'
            for local, frame in enumerate(page_frames):
                x, y = local % columns * CELL, local // columns * CELL
                painter.drawImage(x, y, frame)
                declarations.append({'path': path, 'duration_ms': beats[start + local][1],
                                     'source_rect': [x, y, CELL, CELL]})
            painter.end()
            # These two small clips stay lossless: no palette drift is allowed
            # in the immutable face/lower-body region between moving frames.
            if not atlas.save(str(PET / path)):
                raise OSError(f'Could not save {path}')
        manifest['actions'][action] = {'loop': False, 'frames': declarations}
        scarf = manifest['outfits']['navy_scarf']['actions'][action]
        if len(scarf['frames']) != len(beats):
            raise ValueError('Gesture repair must preserve existing outfit frame slots')
        for declaration, (phase, ms) in zip(scarf['frames'], beats):
            path = declaration['path']
            if path not in scarf_pages:
                with Image.open(PET / path) as image:
                    scarf_pages[path] = image.convert('RGBA')
            x, y, w, h = declaration['source_rect']
            frame = rig.frame(action, phase, scarf=True)
            scarf_pages[path].paste(Image.frombytes('RGBA', (w, h), bytes(frame.constBits())), (x, y))
            declaration['duration_ms'] = ms
        scarf['loop'] = False
    for path, image in scarf_pages.items():
        image.save(PET / path, optimize=True)
    manifest['pack_version'] = '3.5.1'
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    folder = PET / 'outfits/navy_scarf'
    (folder / 'motion.json').write_text(
        json.dumps(manifest['outfits']['navy_scarf'], ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('Repaired 32 greeting and 23 stretch frames in base and navy-scarf outfits.')
    return app


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gestures-only', action='store_true')
    args = parser.parse_args()
    build_gestures() if args.gestures_only else build()
