"""Quiet rest scenery and interruptible entrances, with no perpetual scene clock."""

from __future__ import annotations

import os

from PySide6.QtCore import QEasingCurve, QObject, QPropertyAnimation, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from opencareyes.constants import PETS_DIR


class GentleEntrance(QObject):
    """Only animate a newly shown window; a safety hide always cancels immediately."""

    def __init__(self, widget: QWidget, duration: int = 520):
        super().__init__(widget)
        self.widget = widget
        self.reduced = False
        self.animation = QPropertyAnimation(widget, b"windowOpacity", self)
        self.animation.setDuration(duration)
        self.animation.setEasingCurve(QEasingCurve.OutCubic)

    def configure(self, snapshot) -> None:
        self.reduced = (
            getattr(snapshot, "motion_profile", "standard") == "reduced"
            or bool(getattr(snapshot, "high_contrast", False))
        )
        if self.reduced:
            self.cancel()

    def show(self) -> None:
        if self.widget.isVisible():
            return
        self.animation.stop()
        self.widget.setWindowOpacity(1.0 if self.reduced else 0.0)
        self.widget.show()
        if not self.reduced:
            self.animation.setStartValue(0.0)
            self.animation.setEndValue(1.0)
            self.animation.start()

    def cancel(self) -> None:
        self.animation.stop()
        self.widget.setWindowOpacity(1.0)


class RestScene(QWidget):
    """A small window on the night, deliberately still so attention can leave."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(176)
        self.setMinimumWidth(220)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.scene = "gaze"
        self.high_contrast = False
        self._pet = QImage(os.path.join(PETS_DIR, "snow_ferret", "rest_sleep.png"))

    def configure(self, scene: str, high_contrast: bool) -> None:
        self.scene = scene
        self.high_contrast = high_contrast
        self.setVisible(not high_contrast)
        self.update()

    def paintEvent(self, _event) -> None:
        if self.high_contrast:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.translate(self.width() / 2 - 148, 0)
        frame = QRectF(46, 7, 178, 138)
        clip = QPainterPath()
        clip.addRoundedRect(frame, 28, 28)
        p.save()
        p.setClipPath(clip)
        p.fillRect(frame, QColor("#263D49" if self.scene != "sleep" else "#373747"))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#A9C3B6"))
        p.drawEllipse(QRectF(172, 25, 19, 19))
        hill = QPainterPath()
        hill.moveTo(35, 133)
        hill.cubicTo(98, 66, 128, 123, 165, 88)
        hill.cubicTo(195, 65, 211, 104, 245, 81)
        hill.lineTo(245, 160)
        hill.lineTo(35, 160)
        p.fillPath(hill, QColor("#365351"))
        hill = QPainterPath()
        hill.moveTo(35, 151)
        hill.cubicTo(100, 96, 164, 147, 245, 118)
        hill.lineTo(245, 164)
        hill.lineTo(35, 164)
        p.fillPath(hill, QColor("#2B4343"))
        p.restore()
        p.setPen(QPen(QColor("#5A7778"), 2))
        p.drawLine(135, 8, 135, 142)
        p.drawLine(47, 81, 223, 81)
        p.drawLine(32, 147, 240, 147)
        if not self._pet.isNull():
            p.setOpacity(0.84)
            p.drawImage(QRectF(159, 87, 98, 84), self._pet)
