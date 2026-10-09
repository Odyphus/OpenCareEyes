"""Bake two gestures with fixed-length arms and an unchanged body plate.

Shoulders and elbows drive a continuous painted limb contour. The face, hips,
feet and tail never participate in a raster warp. Only the small chest region
behind the original resting forelegs uses the generated underpainting.
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPainterPath, QPen


CELL = 384
ROOT = Path(__file__).resolve().parents[1]


def ease(value):
    value = max(0.0, min(1.0, value))
    return value**3 * (10 + value * (-15 + 6 * value))


def beat(progress, points):
    for (start, a), (end, b) in zip(points, points[1:]):
        if progress <= end:
            return a + (b - a) * ease((progress - start) / (end - start))
    return points[-1][1]


def direction(degrees):
    radians = math.radians(degrees)
    return QPointF(math.cos(radians), math.sin(radians))


def normal(vector):
    return QPointF(-vector.y(), vector.x())


class GestureRig:
    """One immutable character underlayer, two independently posed forelegs."""

    def __init__(self, textures):
        self.textures = textures
        with Image.open(ROOT / 'artwork/companion/gesture-underpainting-v10.png') as source:
            if source.size != (1254, 1254):
                raise ValueError('Gesture underpainting must retain its 1254px registration')
            plate = Image.new('RGBA', (CELL, CELL))
            plate.alpha_composite(source.convert('RGBA').crop((326, 170, 1100, 1158)).resize(
                (248, 316), Image.Resampling.LANCZOS), (98, 32))
        mask = Image.new('L', (CELL, CELL))
        # This narrow edit window contains both resting forelegs. All source
        # pixels outside it, including the entire face and lower body, survive.
        draw = ImageDraw.Draw(mask)
        draw.rounded_rectangle((120, 184, 268, 276), radius=9, fill=255)
        self.mask = mask.filter(ImageFilter.GaussianBlur(2))
        self.wave_mask = self.mask.copy()
        ImageDraw.Draw(self.wave_mask).rectangle((192, 0, CELL, CELL), fill=0)
        self.plate = plate

    @staticmethod
    def pose(action, progress):
        """Angles in screen coordinates; lengths and shoulder roots stay fixed."""
        raised = beat(progress, ((0, 0), (.08, 0), (.32, 1),
                                 (.72, 1), (.96, 0), (1, 0)))
        if action == 'rest_prompt':
            upper = 104 + (200 - 104) * raised
            fore = 64 + (280 - 64) * raised
            # Two wrist-led sweeps; their envelope starts/ends with zero speed.
            if .32 < progress < .72:
                phase = (progress - .32) / .40
                fore += 15 * math.sin(math.tau * 2 * phase) * math.sin(math.pi * phase)**2
            return ((upper, fore), (104, 64)), raised
        upper = 104 + (224 - 104) * raised
        fore = 64 + (254 - 64) * raised
        return ((upper, fore), (upper, fore)), raised

    @staticmethod
    def arm_joints(side, angles):
        shoulder = QPointF(144, 189)
        upper, fore = map(direction, angles)
        elbow = shoulder + upper * 38
        paw = elbow + fore * 29
        if side:
            shoulder, elbow, paw = (QPointF(382 - p.x(), p.y()) for p in (shoulder, elbow, paw))
            upper, fore = (QPointF(-p.x(), p.y()) for p in (upper, fore))
        return shoulder, elbow, paw, upper, fore

    @classmethod
    def paint_arm(cls, painter, side, angles, pads):
        shoulder, elbow, paw, upper, fore = cls.arm_joints(side, angles)
        nu, nf = normal(upper), normal(fore)
        root_a = shoulder + nu * 16
        edges = ([], [])
        for index in range(41):
            t = index / 40
            # A smooth centreline rounds the elbow rather than producing a
            # rectangular corner. Joint locations and reach remain fixed.
            point = shoulder * (1-t)**3 + elbow * (3*t*(1-t)) + paw * t**3
            tangent = (elbow - shoulder) * (3*(1-t)**2) + (paw - elbow) * (3*t**2)
            tangent /= max(math.hypot(tangent.x(), tangent.y()), .001)
            width = 16 - 3 * t + 1.8 * math.sin(math.pi * t)
            edges[0].append(point + normal(tangent) * width)
            edges[1].append(point - normal(tangent) * width)
        outer_p, inner_p = edges[0][-1], edges[1][-1]
        tip = paw + fore * 14
        contour = QPainterPath(root_a)
        for point in edges[0][1:]:
            contour.lineTo(point)
        contour.cubicTo(outer_p + fore * 12, tip + nf * 10, tip)
        contour.cubicTo(tip - nf * 10, inner_p + fore * 12, inner_p)
        for point in reversed(edges[1][:-1]):
            contour.lineTo(point)
        fill = QPainterPath(contour)
        fill.closeSubpath()
        gradient = QLinearGradient(shoulder + nu * 19, paw - nf * 15)
        gradient.setColorAt(0, QColor('#E4EFFB'))
        gradient.setColorAt(.35, QColor('#F7FAFE'))
        gradient.setColorAt(1, QColor('#FEFEFF'))
        painter.fillPath(fill, gradient)
        # Deliberately leave the root open: a closed black shoulder cap looks
        # like a detached limb pasted on top of the chest.
        painter.setPen(QPen(QColor('#343B44'), 2.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.drawPath(contour)
        painter.setPen(QPen(QColor('#C4DAF4'), 1.5, Qt.SolidLine, Qt.RoundCap))
        fur = QPainterPath(shoulder + upper * 9 - nu * 11)
        fur.quadTo(shoulder + upper * 19 - nu * 12, elbow - nu * 9)
        painter.drawPath(fur)
        cls.paint_paw(painter, paw, fore, pads)

    @staticmethod
    def paint_paw(painter, paw, fore, pads):
        painter.save()
        painter.translate(paw)
        # Local +Y points along the forearm; the palm never scales or skews.
        painter.rotate(math.degrees(math.atan2(fore.y(), fore.x())) - 90)
        painter.setPen(QPen(QColor('#67758A'), 1.3, Qt.SolidLine, Qt.RoundCap))
        painter.setOpacity(1 - pads)
        for x in (-4.5, 4.5):
            line = QPainterPath(QPointF(x, 13))
            line.quadTo(QPointF(x - 1.7, 8), QPointF(x - 1, 5))
            painter.drawPath(line)
        painter.setOpacity(pads)
        painter.setPen(QPen(QColor('#B7737E'), 1.1))
        painter.setBrush(QColor('#F1B4BD'))
        for box in (QRectF(-9, 2, 5, 6), QRectF(-2.5, 5, 5, 6), QRectF(4, 2, 5, 6)):
            painter.drawEllipse(box)
        pad = QPainterPath(QPointF(-6, -5))
        pad.cubicTo(QPointF(-5, -11), QPointF(5, -11), QPointF(6, -5))
        pad.cubicTo(QPointF(8, 1), QPointF(3, 2), QPointF(0, 0))
        pad.cubicTo(QPointF(-3, 2), QPointF(-8, 1), QPointF(-6, -5))
        painter.drawPath(pad)
        painter.restore()

    def frame(self, action, progress):
        if progress <= .04 or progress >= .98:
            return self.textures['head', False]
        angles, raised = self.pose(action, progress)
        expression = 'head'
        if action == 'yawn':
            expression = 'closed' if raised > .72 else 'half' if raised > .4 else 'head'
        original = self.textures[expression, False]
        bitmap = Image.composite(self.plate, original,
                                 self.wave_mask if action == 'rest_prompt' else self.mask)
        image = QImage(bitmap.tobytes(), CELL, CELL, QImage.Format_RGBA8888).copy()
        painter = QPainter(image)
        painter.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        pads = ease((raised - .12) / .58)
        self.paint_arm(painter, 0, angles[0], pads)
        if action == 'yawn':
            self.paint_arm(painter, 1, angles[1], pads)
        # The shoulder roots pass under the unchanged neck ruff. The hands
        # stay in front of the cheeks while the small collar hides the root.
        head = Image.new('RGBA', (CELL, CELL))
        head.alpha_composite(original.crop((0, 170, CELL, 186)), (0, 170))
        painter.drawImage(0, 0, QImage(head.tobytes(), CELL, CELL, QImage.Format_RGBA8888))
        chest_mask = Image.new('L', (CELL, CELL))
        chest = ImageDraw.Draw(chest_mask)
        chest.polygon(((144, 184), (238, 184), (245, 214), (137, 214)), fill=255)
        chest_mask = chest_mask.filter(ImageFilter.GaussianBlur(3))
        if action == 'rest_prompt':
            ImageDraw.Draw(chest_mask).rectangle((192, 0, CELL, CELL), fill=0)
        chest_layer = bitmap.copy()
        chest_layer.putalpha(chest_mask)
        painter.drawImage(0, 0, QImage(chest_layer.tobytes(), CELL, CELL, QImage.Format_RGBA8888))
        painter.end()
        painted = Image.frombytes('RGBA', (CELL, CELL), bytes(image.constBits()))
        # Transition only between two nearly coincident resting forelegs. The
        # character plate is never morphed; this short local fade hides the
        # change from the original painted paw texture to the articulated arm.
        coverage = min(ease((progress - .04) / .04), ease((.98 - progress) / .02))
        result = Image.blend(original, painted, coverage)
        # Preserve even the translucent fur/transparent RGB at the chest-mask
        # boundary. Drawing/compositing can otherwise round a few fringe pixels
        # despite the lower body never moving.
        result.paste(self.textures['head', False].crop((0, 272, CELL, CELL)), (0, 272))
        return result
