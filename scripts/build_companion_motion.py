"""Bake a registered 2D cutout rig into bounded, dependency-free pet atlases.

The authored pivots, shared scale and easing below are the motion source. The
desktop player keeps its existing deadline clock, cache limits and safety rules.
Run from the repository root: python -m scripts.build_companion_motion
"""

from __future__ import annotations

import json
import hashlib
import math
import os
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PIL import Image  # noqa: E402
from PySide6.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPainterPath, QPen  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PET = ROOT / 'assets/pets/snow_ferret'
CELL = 384


class CutoutRig:
    def __init__(self):
        source = ROOT / 'artwork/companion/rig-parts.png'
        self.parts = {}
        names = ('head', 'half', 'closed', 'left', 'body', 'tail', 'arm_l',
                 'arm_r', 'foot_l', 'foot_r', 'sleep', 'read')
        with Image.open(source) as sheet:
            for index, name in enumerate(names):
                row, column = divmod(index, 4)
                box = (column * 384, round(row * 1024 / 3),
                       (column + 1) * 384, round((row + 1) * 1024 / 3))
                if name == 'read':
                    box = (1152, 640, 1536, 1024)
                elif name == 'arm_r':
                    # The authored reading pose extends above its nominal cell.
                    box = (1152, 341, 1536, 630)
                part = sheet.crop(box)
                bounds = part.getchannel('A').point(lambda alpha: 255 if alpha > 12 else 0).getbbox()
                if bounds is None:
                    raise ValueError(f'Empty rig part: {name}')
                part = part.crop(bounds)
                image = QImage(part.tobytes(), part.width, part.height, QImage.Format_RGBA8888).copy()
                self.parts[name] = image

    def part(self, painter, name, rect, *, angle=0.0, pivot=None, mirror=False):
        image = self.parts[name]
        target = QRectF(*rect)
        # Expressions are registered to one head box; limb pivots never change.
        reference = image
        scale = min(target.width() / reference.width(), target.height() / reference.height())
        width, height = image.width() * scale, image.height() * scale
        destination = QRectF(target.center().x() - width / 2, target.bottom() - height, width, height)
        painter.save()
        anchor = QPointF(*(pivot or (target.center().x(), target.top())))
        painter.translate(anchor)
        painter.rotate(angle)
        painter.translate(-anchor)
        if mirror:
            painter.translate(2 * target.center().x(), 0)
            painter.scale(-1, 1)
        painter.drawImage(destination, image)
        painter.restore()

    def frame(self, action='idle', progress=0.0, *, expression='head', scarf=False):
        result = QImage(CELL, CELL, QImage.Format_RGBA8888)
        result.fill(Qt.transparent)
        p = QPainter(result)
        p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        if action == 'sleep' and scarf:
            action, expression = 'idle', 'closed'
        if action in {'sleep', 'read'}:
            rect = (50, 116, 278, 232) if action == 'sleep' else (74, 26, 245, 323)
            self.part(p, action, rect)
            p.end()
            return result

        phase = progress * math.tau
        envelope = math.sin(math.pi * progress) ** 2
        bob = 0.0
        head_angle = 0.0
        tail_angle = 0.0
        arm_l, arm_r = -4.0, 4.0
        leg_l, leg_r = 0.0, 0.0
        head_shift = 0.0
        body_scale = 1.0
        mirror_head = False
        if action == 'move':
            leg_l, leg_r = 9 * math.sin(phase), -9 * math.sin(phase)
            arm_l, arm_r = -5 + 14 * math.sin(phase), 5 - 14 * math.sin(phase)
            bob = -3 * math.cos(2 * phase)
            tail_angle = 5 * math.sin(phase + 0.7)
            head_angle = 2 * math.sin(phase)
        elif action == 'click_reaction':
            head_angle = -9 * envelope
            arm_r = -65 * envelope
            bob = -7 * envelope
            tail_angle = 10 * envelope
            expression = 'closed' if 0.25 < progress < 0.75 else 'head'
        elif action == 'play':
            head_angle = 9 * math.sin(phase) * envelope
            arm_l = 32 * envelope
            arm_r = -48 * envelope
            bob = -9 * envelope
            tail_angle = 12 * math.sin(phase) * envelope
        elif action == 'drag_hold':
            arm_l, arm_r = 30, -30
            leg_l, leg_r = 7, 7
            head_angle = 3 * math.sin(phase)
            body_scale = 1.04
        elif action == 'drag_release':
            body_scale = 1.0 - 0.07 * math.sin(math.pi * progress)
            bob = 6 * envelope
            head_angle = 4 * math.sin(phase) * (1 - progress)
        elif action == 'right_click_reaction':
            head_angle = 11 * envelope
            arm_l, arm_r = -4 - 17 * envelope, 4 + 17 * envelope
            expression = 'half' if envelope > 0.6 else 'head'
        elif action in {'rest_prompt', 'yawn'}:
            arm_l, arm_r = 48 * envelope, -48 * envelope
            head_angle = -7 * envelope
            expression = 'closed' if action == 'yawn' and envelope > 0.6 else 'head'
        elif action.startswith('look_'):
            direction = -1 if action == 'look_left' else 1 if action == 'look_right' else 0
            eased = 1 - (1 - progress) ** 3
            head_shift = 5 * direction * eased
            head_angle = 5 * direction * eased
            if direction and progress > 0.6:
                expression = 'left'
                mirror_head = direction > 0

        # Tail behind the torso; all pivots stay in the same 384px coordinate space.
        self.part(p, 'tail', (207, 230 + bob, 120, 110), angle=tail_angle, pivot=(215, 316))
        self.part(p, 'foot_l', (104, 319 + leg_l, 54, 33))
        self.part(p, 'foot_r', (178, 319 + leg_r, 54, 33))
        self.part(p, 'body', (103, 170 + bob, 131, 169 * body_scale))
        self.part(p, 'arm_l', (96, 197 + bob, 46, 85), angle=arm_l, pivot=(118, 202 + bob))
        self.part(p, 'arm_r', (192, 197 + bob, 46, 85), angle=arm_r, pivot=(216, 202 + bob))
        if scarf:
            fabric = QPainterPath()
            fabric.moveTo(124, 198 + bob)
            fabric.cubicTo(148, 210 + bob, 180, 210 + bob, 216, 194 + bob)
            fabric.lineTo(214, 218 + bob)
            fabric.cubicTo(184, 225 + bob, 157, 224 + bob, 139, 218 + bob)
            fabric.lineTo(140, 255 + bob)
            fabric.lineTo(120, 249 + bob)
            fabric.closeSubpath()
            p.setPen(QPen(QColor('#29445D'), 2))
            p.setBrush(QColor('#4C718E'))
            p.drawPath(fabric)
        self.part(p, expression, (65 + head_shift, 32 + bob, 213, 183),
                  angle=head_angle, pivot=(171, 193 + bob), mirror=mirror_head)
        if action == 'play':
            x = 278 - 30 * math.sin(phase) * envelope
            y = 324 - 18 * envelope
            p.setPen(QPen(QColor('#63897D'), 2))
            p.setBrush(QColor('#A9CDB9'))
            p.drawEllipse(QRectF(x, y, 22, 22))
            p.drawArc(QRectF(x + 6, y, 10, 22), 90 * 16, 180 * 16)
        p.end()
        return result


def build():
    app = QGuiApplication.instance() or QGuiApplication([])
    rig = CutoutRig()
    manifest_path = PET / 'manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    clips = {}
    idle_expressions = ['head', 'half', 'closed', 'half', 'head', 'half', 'closed', 'half', 'head']
    clips['idle'] = ([rig.frame(expression=name) for name in idle_expressions],
                     [2600, 80, 65, 80, 2400, 80, 65, 80, 1400], True)
    for action, count, duration, loop in (
        ('move', 16, 60, True), ('click_reaction', 15, 60, False),
        ('play', 21, 60, False), ('drag_hold', 12, 80, True),
        ('drag_release', 13, 60, False), ('right_click_reaction', 15, 60, False),
        ('rest_prompt', 17, 60, False), ('yawn', 19, 80, False),
        ('look_left', 7, 60, False), ('look_center', 7, 60, False),
        ('look_right', 7, 60, False),
    ):
        frames = [rig.frame(action, index / (count if loop else count - 1)) for index in range(count)]
        clips[action] = (frames, [duration] * count, loop)
    clips['sleep'] = ([rig.frame('sleep')], [5000], True)
    clips['read'] = ([rig.frame('read')], [5000], True)
    clips['look_cursor'] = ([rig.frame('look_left', 1), rig.frame(), rig.frame('look_right', 1)],
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
            declarations.append({'path': f'sprites/calm_{action}.png',
                                 'duration_ms': durations[index], 'source_rect': [x, y, CELL, CELL]})
        painter.end()
        raw = Image.frombytes('RGBA', (atlas.width(), atlas.height()), bytes(atlas.constBits()))
        # One palette per whole clip keeps colour stable across all its frames.
        # Indexed PNG cuts package/decode cost without adding a runtime codec.
        raw.quantize(colors=256, method=Image.Quantize.FASTOCTREE,
                     dither=Image.Dither.NONE).save(PET / f'sprites/calm_{action}.png', optimize=True)
        manifest['actions'][action] = {'loop': loop, 'frames': declarations}
    manifest['pack_version'] = '3.1.0'
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
        ('idle', 5, 100, True), ('sleep', 1, 5000, True),
        ('move', 12, 80, True), ('click_reaction', 7, 100, False),
        ('drag_hold', 1, 800, True), ('drag_release', 7, 80, False),
        ('right_click_reaction', 7, 100, False), ('rest_prompt', 7, 120, False),
        ('play', 7, 120, False), ('look_cursor', 3, 600, False),
    ):
        declarations = []
        for index in range(count):
            phase = index / max(1, count if loop else count - 1)
            if action == 'idle':
                pose = rig.frame(expression=['head', 'half', 'closed', 'half', 'head'][index], scarf=True)
                ms = [3000, 80, 65, 80, 2400][index]
            elif action == 'look_cursor':
                pose = rig.frame(['look_left', 'idle', 'look_right'][index], 1, scarf=True)
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
    for start in range(0, len(frames), 16):
        atlas = QImage(CELL * 4, CELL * 4, QImage.Format_RGBA8888)
        atlas.fill(Qt.transparent)
        painter = QPainter(atlas)
        for cell, frame in enumerate(frames[start:start + 16]):
            painter.drawImage((cell % 4) * CELL, (cell // 4) * CELL, frame)
        painter.end()
        raw = Image.frombytes('RGBA', (atlas.width(), atlas.height()), bytes(atlas.constBits()))
        raw.quantize(colors=256, method=Image.Quantize.FASTOCTREE,
                     dither=Image.Dither.NONE).save(folder / f'motion_{start // 16 + 1}.png', optimize=True)
    outfit['actions'] = actions
    outfit['description'] = '柔软的暮蓝围巾，陪你读书，也陪你休息。采用同一分层角色制作连贯动作。'
    (folder / 'motion.json').write_text(json.dumps(outfit, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    rig.frame(scarf=True).scaled(512, 512, Qt.KeepAspectRatio, Qt.SmoothTransformation).save(str(folder / 'preview.png'))
    rig.frame(scarf=True).scaled(256, 256, Qt.KeepAspectRatio, Qt.SmoothTransformation).save(str(folder / 'thumbnail.png'))


if __name__ == '__main__':
    build()
