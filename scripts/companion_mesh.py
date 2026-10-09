"""Bake connected character motion, with articulated arms for two gestures.

All tiles share the same inverse displacement field and boundary vertices.
Greeting/stretch use a fixed body plate and rounded joint-driven arm contours.
This is a build-time 2D image deformation, not a Live2D/Cubism runtime.
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageOps
from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen

ROOT = Path(__file__).resolve().parents[1]
CELL = 384
SOURCE_BOX = (326, 170, 1100, 1158)
DESTINATION = (98, 32, 248, 316)
EYE_WINDOWS = ((436, 345, 560, 480), (683, 345, 807, 480))


def smoothstep(low, high, value):
    t = max(0.0, min(1.0, (value - low) / (high - low)))
    return t * t * (3 - 2 * t)


def keyed(progress, points):
    """Ease between authored beats; holds and recovery are explicit."""
    for (start, a), (end, b) in zip(points, points[1:]):
        if progress <= end:
            return a + (b - a) * smoothstep(start, end, progress)
    return points[-1][1]


def qimage(bitmap):
    return QImage(bitmap.tobytes(), bitmap.width, bitmap.height, QImage.Format_RGBA8888).copy()


class CoherentRig:
    def __init__(self):
        if __package__:
            from .companion_keyposes import CompletePoses
        else:
            from companion_keyposes import CompletePoses
        self.poses = CompletePoses()
        folder = ROOT / 'artwork/companion'
        with Image.open(folder / 'coherent-neutral-v3.png') as image:
            neutral = image.convert('RGBA')
        eye_mask = Image.new('L', neutral.size)
        draw = ImageDraw.Draw(eye_mask)
        for box in EYE_WINDOWS:
            draw.rounded_rectangle(box, radius=16, fill=255)
        eye_mask = eye_mask.filter(ImageFilter.GaussianBlur(3))
        self.textures = {}
        for expression, name in (('head', 'neutral'), ('half', 'half'), ('closed', 'closed')):
            with Image.open(folder / f'coherent-{name}-v3.png') as image:
                if image.size != neutral.size:
                    raise ValueError('Expression source registration changed')
                # Only use the generated eyelids. All fur, silhouette, body and
                # paws retain the exact neutral pixels throughout a blink.
                source = neutral if name == 'neutral' else Image.composite(image.convert('RGBA'), neutral, eye_mask)
            x, y, width, height = DESTINATION
            bitmap = Image.new('RGBA', (CELL, CELL))
            bitmap.alpha_composite(source.crop(SOURCE_BOX).resize((width, height), Image.Resampling.LANCZOS), (x, y))
            self.textures[(expression, False)] = bitmap
            self.textures[(expression, True)] = self._scarf(bitmap)
        self.static = {}
        self._motion_cache = {}
        if __package__:
            from .companion_gestures import GestureRig
        else:
            from companion_gestures import GestureRig
        self.gestures = GestureRig(self.textures)
        with Image.open(folder / 'rig-parts.png') as sheet:
            for action, box, target in (
                ('sleep', (768, 683, 1152, 1024), (50, 116, 278, 232)),
                ('read', (1152, 640, 1536, 1024), (74, 26, 245, 323)),
            ):
                pose = sheet.crop(box)
                bounds = pose.getchannel('A').point(lambda a: 255 if a > 12 else 0).getbbox()
                if bounds is None:
                    raise ValueError(f'Empty complete pose: {action}')
                pose = pose.crop(bounds)
                x, y, w, h = target
                scale = min(w / pose.width, h / pose.height)
                size = (round(pose.width * scale), round(pose.height * scale))
                bitmap = Image.new('RGBA', (CELL, CELL))
                bitmap.alpha_composite(pose.resize(size, Image.Resampling.LANCZOS),
                                       (round(x + (w - size[0]) / 2), y + h - size[1]))
                self.static[action] = bitmap

    @staticmethod
    def _scarf(bitmap, *, walk_index=None):
        image = qimage(bitmap)
        painter = QPainter(image)
        painter.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        fabric = QPainterPath()
        if walk_index is not None:
            painter.translate(0, (0, -3, 7, 3)[walk_index])
            fabric.moveTo(261, 256)
            fabric.cubicTo(271, 268, 289, 277, 305, 279)
            fabric.lineTo(302, 288)
            fabric.cubicTo(285, 285, 266, 276, 256, 264)
            fabric.closeSubpath()
            fabric.moveTo(282, 278)
            fabric.lineTo(294, 284)
            fabric.lineTo(291, 309)
            fabric.lineTo(280, 304)
            fabric.closeSubpath()
            painter.setPen(QPen(QColor('#29445D'), 1.6))
            painter.setBrush(QColor('#4C718E'))
            painter.drawPath(fabric)
            painter.end()
            return Image.frombytes('RGBA', (CELL, CELL), bytes(image.constBits()))
        painter.translate(22, 0)
        fabric.moveTo(123, 174)
        fabric.cubicTo(149, 183, 193, 183, 216, 172)
        fabric.lineTo(214, 187)
        fabric.cubicTo(187, 198, 151, 198, 125, 187)
        fabric.closeSubpath()
        fabric.moveTo(137, 186)
        fabric.lineTo(155, 192)
        fabric.lineTo(151, 222)
        fabric.lineTo(132, 218)
        fabric.closeSubpath()
        painter.setPen(QPen(QColor('#29445D'), 1.6))
        painter.setBrush(QColor('#4C718E'))
        painter.drawPath(fabric)
        painter.end()
        return Image.frombytes('RGBA', (CELL, CELL), bytes(image.constBits()))

    @staticmethod
    def displacement(action, progress, x, y, *, gaze=None):
        phase = math.tau * progress
        envelope = math.sin(math.pi * progress) ** 2
        head = 1 - smoothstep(147, 240, y)
        upper = 1 - smoothstep(284, 339, y)
        torso = math.exp(-((y - 255) / 75) ** 2)
        breath = 0.9 * math.sin(phase * 2)
        bob = angle = shift = 0.0
        left_x = left_y = right_x = right_y = 0.0
        left_foot = right_foot = 0.0
        tail = 0.0
        squash = 0.0
        if action == 'idle':
            angle = keyed(progress, ((0, 0), (.10, 0), (.18, -7), (.28, -7),
                                      (.39, 0), (.55, 0), (.64, 5), (.72, 5),
                                      (.82, 0), (1, 0)))
            tail = 11 * math.sin(phase * 3) * keyed(progress, (
                (0, 0), (.10, 0), (.18, 1), (.32, 1), (.40, 0),
                (.56, 0), (.64, 1), (.80, 1), (.90, 0), (1, 0)))
        elif action == 'click_reaction':
            angle = keyed(progress, ((0, 0), (.14, 3), (.28, -5), (.55, -5), (.8, 2), (1, 0)))
            tail = 14 * math.sin(phase * 1.5) * envelope
            left_y = right_y = -3 * envelope
        elif action == 'play':
            angle = 5 * math.sin(phase * 2) * envelope
            tail = 16 * math.sin(phase * 2 - .5) * envelope
            left_y, right_y = -3 * envelope, -5 * envelope
        elif action == 'drag_hold':
            angle, bob = 3 * math.sin(phase), -2
            left_y = right_y = 4
            left_foot = right_foot = 5
            tail = 8 * math.sin(phase - .7)
        elif action == 'drag_release':
            angle = 4 * math.sin(phase * 1.5) * (1 - progress)
            tail = 10 * math.sin(phase - .7) * (1 - progress)
        elif action == 'right_click_reaction':
            angle = keyed(progress, ((0, 0), (.18, 8), (.52, 8), (.78, -2), (1, 0)))
            shift = 3 * envelope
            tail = 9 * math.sin(phase) * envelope
        elif action in {'rest_prompt', 'yawn'}:
            angle = -4 * envelope
            left_x, right_x = -3 * envelope, 3 * envelope
            left_y = right_y = -5 * envelope
            tail = 9 * math.sin(phase - .4) * envelope
        elif action.startswith('look_'):
            direction = -1 if action == 'look_left' else 1 if action == 'look_right' else 0
            eased = 1 - (1 - progress) ** 3
            angle, shift = direction * 6 * eased, direction * 7 * eased
            breath = tail = 0

        if gaze is not None:
            horizontal, vertical = gaze
            angle, shift = horizontal * 3.5, horizontal * 8
            breath = tail = 0
        radians = math.radians(angle)
        rx, ry = x - 192, y - 177
        dx = head * (rx * (math.cos(radians) - 1) - ry * math.sin(radians) + shift)
        dy = head * (rx * math.sin(radians) + ry * (math.cos(radians) - 1))
        if gaze is not None:
            dx += head * gaze[0] * .035 * (abs(rx) - 60)
            dy += head * gaze[1] * 7
            for eye_x in (153, 230):
                eye = math.exp(-((x - eye_x) / 28) ** 2 - ((y - 102) / 32) ** 2)
                dx += eye * gaze[0] * 5
                dy += eye * gaze[1] * 4
        dx += torso * (x - 192) * (0.008 * breath + squash)
        dy += upper * (bob - 0.5 * breath) + torso * (y - 270) * (-squash)
        for cx, mx, my in ((159, left_x, left_y), (225, right_x, right_y)):
            influence = math.exp(-((x - cx) / 30) ** 2 - ((y - 254) / 48) ** 2) * smoothstep(190, 226, y)
            dx += influence * mx
            dy += influence * my
        foot = smoothstep(308, 342, y)
        dy += foot * (left_foot * math.exp(-((x - 153) / 30) ** 2)
                      + right_foot * math.exp(-((x - 233) / 30) ** 2))
        # A tail swings around its base. Translating its tip sideways made the
        # previous version look like a soft sliding patch.
        tail_weight = smoothstep(245, 325, x) * smoothstep(166, 310, y)
        tr = math.radians(tail)
        tx, ty = x - 260, y - 312
        dx += tail_weight * (tx * (math.cos(tr) - 1) - ty * math.sin(tr))
        dy += tail_weight * (tx * math.sin(tr) + ty * (math.cos(tr) - 1))
        return dx, dy

    @staticmethod
    def body_motion(action, progress):
        """Return horizontal/vertical scale and jump height, about planted feet."""
        if action in {'click_reaction', 'play'}:
            p = progress if action == 'click_reaction' else (progress * 2) % 1
            rise = keyed(p, ((0, 0), (.16, 0), (.28, 9), (.46, 24),
                              (.56, 24), (.76, 0), (1, 0)))
            squeeze = keyed(p, ((0, 0), (.14, 1), (.25, -.25), (.38, 0),
                                 (.68, 0), (.80, 1), (.91, -.15), (1, 0)))
            return 1 + squeeze * .045, 1 - squeeze * .055, rise
        if action == 'drag_release':
            squeeze = keyed(progress, ((0, 0), (.18, 1), (.42, -.25), (.68, .15), (1, 0)))
            return 1 + squeeze * .055, 1 - squeeze * .07, 0
        if action == 'yawn':
            stretch = keyed(progress, ((0, 0), (.18, -.25), (.44, 1), (.68, 1), (1, 0)))
            return 1 - stretch * .025, 1 + stretch * .04, 0
        return 1, 1, 0

    @staticmethod
    def finish(bitmap):
        # Keep room for ears at the jump apex and for the tail arc. A uniform
        # registration scale applies to every pose, including static previews.
        scale = .95
        bitmap = bitmap.transform((CELL, CELL), Image.Transform.AFFINE,
            (1 / scale, 0, 192 - 192 / scale, 0, 1 / scale, 348 - 348 / scale),
            Image.Resampling.BICUBIC)
        return qimage(bitmap)

    @classmethod
    def mesh(cls, action, progress, *, gaze=None):
        # Each vertex is computed once and shared by adjacent tiles. Quad order
        # is upper-left, lower-left, lower-right, upper-right (Pillow MESH).
        step = 16
        vertices = {}
        for y in range(0, CELL + 1, step):
            for x in range(0, CELL + 1, step):
                dx, dy = cls.displacement(action, progress, x, y, gaze=gaze)
                vertices[x, y] = (x - dx, y - dy)
        return [((x, y, x + step, y + step), tuple(
            coordinate for vertex in ((x, y), (x, y + step), (x + step, y + step), (x + step, y))
            for coordinate in vertices[vertex]))
            for y in range(0, CELL, step) for x in range(0, CELL, step)]

    def frame(self, action='idle', progress=0.0, *, expression='head', scarf=False):
        if action.startswith('look_') and action[5:] in self.poses.gaze:
            bitmap = self.poses.gaze[action[5:]]
            return self.finish(self._scarf(bitmap) if scarf else bitmap)
        if action == 'sleep' and scarf:
            action, expression = 'idle', 'closed'
        if action in self.static:
            return self.finish(self.static[action])
        if action == 'move':
            phase = progress * 4 % 4
            index = int(phase)
            bitmap = self._walk_between(index, phase - index)
            bitmap = self._walking_scarf(bitmap) if scarf else bitmap
            # PetSurface mirrors right-facing movement; source art is left.
            return self.finish(ImageOps.mirror(bitmap))
        if action == 'rest_prompt':
            bitmap = self._greeting_frame(progress)
            return self.finish(self._scarf(bitmap) if scarf else bitmap)
        if action == 'yawn':
            bitmap = self._stretch_frame(progress)
            return self.finish(self._scarf(bitmap) if scarf else bitmap)
        envelope = math.sin(math.pi * progress) ** 2
        if action == 'click_reaction' and 0.38 < progress < 0.62:
            expression = 'closed'
        elif action == 'yawn' and envelope > 0.6:
            expression = 'closed'
        elif action == 'right_click_reaction' and envelope > 0.6:
            expression = 'half'
        bitmap = self.textures[(expression, bool(scarf))].transform(
            (CELL, CELL), Image.Transform.MESH, self.mesh(action, progress), Image.Resampling.BICUBIC)
        sx, sy, rise = self.body_motion(action, progress)
        if (sx, sy, rise) != (1, 1, 0):
            bitmap = bitmap.transform((CELL, CELL), Image.Transform.AFFINE,
                (1 / sx, 0, 192 - 192 / sx, 0, 1 / sy, 348 + (rise - 348) / sy),
                Image.Resampling.BICUBIC)
        image = self.finish(bitmap)
        if action == 'play':
            painter = QPainter(image)
            painter.setRenderHint(QPainter.Antialiasing)
            x = 300 + 30 * math.sin(progress * math.tau)
            y = 326 - 54 * abs(math.sin(progress * math.tau * 2))
            painter.setPen(QPen(QColor('#63897D'), 2))
            painter.setBrush(QColor('#A9CDB9'))
            painter.drawEllipse(QRectF(x, y, 22, 22))
            painter.drawArc(QRectF(x + 6, y, 10, 22), 90 * 16, 180 * 16)
            painter.end()
        return image

    def gaze_frame(self, horizontal, vertical, *, scarf=False):
        bitmap = self.textures['head', bool(scarf)].transform(
            (CELL, CELL), Image.Transform.MESH,
            self.mesh('gaze', 0, gaze=(horizontal, vertical)), Image.Resampling.BICUBIC)
        return self.finish(bitmap)

    @staticmethod
    def _walking_scarf(bitmap):
        image = qimage(bitmap)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing)
        fabric = QPainterPath()
        fabric.moveTo(262, 261)
        fabric.cubicTo(273, 273, 290, 280, 298, 280)
        fabric.lineTo(293, 290)
        fabric.cubicTo(278, 289, 265, 280, 255, 271)
        fabric.closeSubpath()
        fabric.moveTo(270, 280)
        fabric.lineTo(281, 285)
        fabric.lineTo(275, 309)
        fabric.lineTo(263, 303)
        fabric.closeSubpath()
        painter.setPen(QPen(QColor('#29445D'), 1.6))
        painter.setBrush(QColor('#4C718E'))
        painter.drawPath(fabric)
        painter.end()
        return Image.frombytes('RGBA', (CELL, CELL), bytes(image.constBits()))

    @staticmethod
    def _morph(first, second, phase, points_a, points_b):
        if __package__:
            from .companion_pose_morph import morph
        else:
            from companion_pose_morph import morph
        return morph(first, second, phase, points_a, points_b)

    @staticmethod
    def _fixed_pose_points():
        if __package__:
            from .companion_pose_morph import fixed_points
        else:
            from companion_pose_morph import fixed_points
        return fixed_points()

    def _walk_between(self, index, phase):
        key = ('walk', index, round(phase, 5))
        if key not in self._motion_cache:
            points = [(0, 0), (384, 0), (0, 384), (384, 384), (192, 264),
                      (319, 238), (321, 263), (70, 258), (140, 301), (222, 307)]
            paws = [((279, 341), (96, 341)), ((260, 341), (130, 341)),
                    ((279, 341), (94, 341)), ((288, 324), (129, 341))]
            self._motion_cache[key] = self._morph(
                self.poses.walk[index], self.poses.walk[(index + 1) % 4],
                phase, points + list(paws[index]), points + list(paws[(index + 1) % 4]))
        return self._motion_cache[key]

    def _greeting_frame(self, progress):
        return self.gestures.frame('rest_prompt', progress)

    def _stretch_frame(self, progress):
        return self.gestures.frame('yawn', progress)
