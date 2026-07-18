'''Stable transparent top-level surface for one desktop companion.'''

from __future__ import annotations

from collections.abc import Mapping

from PySide6.QtCore import (
    QEasingCurve,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRectF,
    QTimer,
    Signal,
    Qt,
)
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication, QWidget

from opencareyes.ui.pet_animator import PetAnimator


class PetSurface(QWidget):
    '''Render a pet pack and translate pointer gestures into semantic signals.

    The window stays alive while packs and actions change. It never reads the
    break timer and never recreates itself for a frame update, which prevents
    pet animation from disturbing the authoritative rest countdown.
    '''

    short_clicked = Signal()
    bubble_requested = Signal()
    right_clicked = Signal()
    drag_started = Signal(QPoint)
    drag_moved = Signal(QPoint)
    drag_finished = Signal(QPoint)
    position_changed = Signal(int, int)
    reset_requested = Signal()
    pet_event = Signal(str, object)
    pack_switched = Signal(str)
    pack_switch_failed = Signal(str, str)

    def __init__(self, repository=None, parent=None):
        super().__init__(parent)
        self._repository = repository
        self._pet_id = ''
        self._manifest = None
        self._frame: QImage | None = None
        self._appearance_paths: tuple[str, ...] = ()
        self._appearance_images: tuple[QImage, ...] = ()
        self._facing_direction = 0
        self._scale_percent = 100
        self._reduced_motion = False
        self._suppressed = False
        self._switch_target = None
        self._switch_snapshot = None
        self._switch_phase = 'idle'
        self._left_pressed = False
        self._right_pressed = False
        self._dragging = False
        self._press_global = QPoint()
        self._drag_offset = QPoint()
        self._drag_threshold = 6
        self._hold_duration_ms = 250

        self.setObjectName('petSurface')
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self.setMouseTracking(True)
        self.setCursor(Qt.OpenHandCursor)
        self.setFixedSize(128, 128)
        self.setAccessibleName('桌面伙伴')
        self.setToolTip('单击互动，长按拖动，右键看看伙伴的反应')

        self.animator = PetAnimator(repository, self)
        self.animator.frame_changed.connect(self._set_frame)
        if repository is not None:
            resource_ready = getattr(repository, 'resource_ready', None)
            resource_failed = getattr(repository, 'resource_failed', None)
            if resource_ready is not None:
                resource_ready.connect(self._on_appearance_resource_ready)
            if resource_failed is not None:
                resource_failed.connect(self._on_appearance_resource_failed)

        self._switch_animation = QPropertyAnimation(
            self,
            b'windowOpacity',
            self,
        )
        self._switch_animation.setDuration(160)
        self._switch_animation.setEasingCurve(QEasingCurve.InOutCubic)
        self._switch_animation.finished.connect(self._switch_animation_finished)

        self._hold_timer = QTimer(self)
        self._hold_timer.setSingleShot(True)
        self._hold_timer.setInterval(self._hold_duration_ms)
        self._hold_timer.timeout.connect(self._begin_drag)

        self._bubble_timer = QTimer(self)
        self._bubble_timer.setSingleShot(True)
        self._bubble_timer.setInterval(300)
        self._bubble_timer.timeout.connect(self.bubble_requested.emit)

        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(5000)
        self._preview_timer.timeout.connect(self._finish_preview)
        self._preview_was_visible = False

    @property
    def pet_id(self) -> str:
        return self._pet_id

    @property
    def action_id(self) -> str:
        return self.animator.action_id

    @property
    def is_dragging(self) -> bool:
        return self._dragging

    @property
    def facing_direction(self) -> int:
        return self._facing_direction

    @property
    def has_asset_frame(self) -> bool:
        return self._frame is not None and not self._frame.isNull()

    def set_pack(self, pet_id: str, manifest) -> bool:
        '''Load the first pack or switch packs without replacing this QWidget.'''

        pet_id = str(pet_id)
        try:
            self._validate_pack(pet_id, manifest)
        except (IndexError, TypeError, ValueError) as exc:
            self.pack_switch_failed.emit(pet_id, str(exc))
            return False

        if (
            self._switch_phase == 'idle'
            and pet_id == self._pet_id
            and manifest is self._manifest
        ):
            return True

        if self._manifest is None:
            try:
                self._apply_pack(pet_id, manifest)
            except (IndexError, RuntimeError, TypeError, ValueError) as exc:
                self._clear_pack()
                self.pack_switch_failed.emit(pet_id, str(exc))
                return False
            self.setWindowOpacity(1.0)
            return True

        return self.switch_pack(pet_id, manifest)

    def switch_pack(self, pet_id: str, manifest) -> bool:
        '''Queue a preloaded pack, keeping only the latest requested target.'''

        pet_id = str(pet_id)
        try:
            self._validate_pack(pet_id, manifest)
        except (IndexError, TypeError, ValueError) as exc:
            self.pack_switch_failed.emit(pet_id, str(exc))
            return False

        requested = (pet_id, manifest)
        if self._switch_target == requested:
            return True
        if (
            self._switch_phase == 'idle'
            and pet_id == self._pet_id
            and manifest is self._manifest
        ):
            return True

        if self._switch_phase == 'idle':
            self._switch_snapshot = self._snapshot_pack()
        self._switch_target = requested
        self.animator.stop(clear_frame=False)

        if not self.isVisible() or self._reduced_motion:
            self._complete_switch_immediately()
        elif self._switch_phase == 'fading_out':
            pass
        else:
            self._start_switch_fade('fading_out', 0.0)
        return True

    def set_manifest(self, pet_id: str, manifest) -> bool:
        '''Compatibility alias used by the first controller integration.'''

        return self.set_pack(pet_id, manifest)

    def play_event(self, event_kind: str, payload=None) -> bool:
        bindings = getattr(self._manifest, 'event_bindings', None)
        action_id = bindings.get(event_kind) if isinstance(bindings, Mapping) else None
        if not action_id:
            action_id = event_kind if self._has_action(event_kind) else 'idle'
        self.pet_event.emit(str(event_kind), payload)
        return self.play_action(str(action_id), restart=True)

    def play_action(self, action_id: str, *, restart: bool = False) -> bool:
        action = self._action(action_id)
        if action is None and action_id != 'idle':
            action_id = 'idle'
            action = self._action(action_id)
        if action is None:
            self.animator.stop(clear_frame=True)
            self.update()
            return False
        return self.animator.play(action_id, action, restart=restart)

    def set_reduced_motion(self, reduced: bool) -> None:
        reduced = bool(reduced)
        if reduced == self._reduced_motion:
            return
        self._reduced_motion = reduced
        self.animator.set_reduced_motion(self._reduced_motion)
        if self._reduced_motion and self._switch_phase != 'idle':
            self._complete_switch_immediately()

    def set_motion_enabled(self, enabled: bool) -> None:
        self.set_reduced_motion(not enabled)

    def set_facing_direction(self, direction: int) -> bool:
        normalised = -1 if int(direction) < 0 else (1 if int(direction) > 0 else 0)
        if normalised == self._facing_direction:
            return False
        self._facing_direction = normalised
        self.update()
        return True

    def face_towards_cursor(
        self,
        global_position: QPoint,
        *,
        dead_zone: int = 12,
    ) -> bool:
        position = QPoint(global_position)
        geometry = self.frameGeometry()
        if geometry.contains(position):
            return False
        horizontal_offset = position.x() - geometry.center().x()
        if abs(horizontal_offset) <= max(0, int(dead_zone)):
            return False
        return self.set_facing_direction(-1 if horizontal_offset < 0 else 1)

    def set_scale_percent(self, percent: int) -> None:
        canvas = getattr(self._manifest, 'canvas_size', (128, 128))
        normalised = max(60, min(int(percent), 200))
        scale = normalised / 100
        self._scale_percent = normalised
        self._set_fixed_size_if_changed(
            max(48, round(int(canvas[0]) * scale)),
            max(48, round(int(canvas[1]) * scale)),
        )

    def set_presentation_visible(self, visible: bool) -> bool:
        '''Apply projected visibility once instead of repeatedly raising the HWND.'''

        visible = bool(visible)
        if visible == self.isVisible():
            return False
        if visible:
            self.show()
            self.raise_()
        else:
            self.hide()
        return True

    def set_suppressed(self, suppressed: bool) -> bool:
        '''Suspend animation and transient pointer timers without changing preference.'''

        suppressed = bool(suppressed)
        if suppressed == self._suppressed:
            return False
        self._suppressed = suppressed
        if suppressed:
            self._hold_timer.stop()
            self._bubble_timer.stop()
            self._preview_timer.stop()
            self._reset_pointer_state()
        self._sync_animation_activity()
        return True

    def set_appearance(self, appearance) -> None:
        slots = (
            'scene',
            'bodywear',
            'neckwear',
            'headwear',
            'held_item',
            'effect',
        )
        paths = tuple(
            str(
                appearance.get(slot, '')
                if isinstance(appearance, Mapping)
                else getattr(appearance, slot, '')
            )
            for slot in slots
        )
        paths = tuple(path for path in paths if path)
        if paths == self._appearance_paths:
            return
        self._appearance_paths = paths
        self._reload_appearance_images(force=True)

    def _reload_appearance_images(self, *, force: bool = False) -> None:
        images: list[QImage] = []
        if self._repository is not None and self._pet_id:
            for path in self._appearance_paths:
                image = self._repository.load_frame(self._pet_id, path)
                if isinstance(image, QImage) and not image.isNull():
                    images.append(QImage(image))
        candidate = tuple(images)
        unchanged = tuple(image.cacheKey() for image in candidate) == tuple(
            image.cacheKey() for image in self._appearance_images
        )
        if unchanged and not force:
            return
        self._appearance_images = candidate
        self.update()

    def _on_appearance_resource_ready(
        self,
        pet_id: str,
        resource_path: str,
    ) -> None:
        if (
            str(pet_id) != self._pet_id
            or str(resource_path) not in self._appearance_paths
        ):
            return
        self._reload_appearance_images()

    def _on_appearance_resource_failed(
        self,
        pet_id: str,
        resource_path: str,
    ) -> None:
        if (
            str(pet_id) != self._pet_id
            or str(resource_path) not in self._appearance_paths
        ):
            return
        self.update()

    def move_to_default(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            self.move(24, 24)
            return
        area = screen.availableGeometry()
        self.move(
            area.right() - self.width() - 23,
            area.bottom() - self.height() - 23,
        )

    def reset_position(self) -> None:
        self.move_to_default()
        self.reset_requested.emit()

    def preview(self) -> None:
        '''Show a short placement preview without changing preferences.'''

        self._preview_was_visible = self.isVisible()
        if not self._preview_was_visible:
            self.move_to_default()
        self.show()
        self.raise_()
        self._preview_timer.start()

    def _finish_preview(self) -> None:
        if not self._preview_was_visible:
            self.hide()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._sync_animation_activity()

    def hideEvent(self, event) -> None:
        if self._switch_phase != 'idle':
            self._complete_switch_immediately()
        self._hold_timer.stop()
        self._bubble_timer.stop()
        self._preview_timer.stop()
        self._reset_pointer_state()
        self._sync_animation_activity(visible=False)
        super().hideEvent(event)

    def closeEvent(self, event) -> None:
        self.hide()
        event.accept()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.save()
        if self._facing_direction > 0:
            painter.translate(self.width(), 0)
            painter.scale(-1, 1)
        if self.has_asset_frame:
            painter.drawImage(self._frame_target_rect(), self._frame)
        else:
            self._paint_fallback(painter)
        for appearance in self._appearance_images:
            painter.drawImage(QRectF(self.rect()), appearance)
        painter.restore()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            if not self._contains_visible_pixel(event.position()):
                event.ignore()
                return
            self._bubble_timer.stop()
            self._left_pressed = True
            self._press_global = event.globalPosition().toPoint()
            self._drag_offset = self._press_global - self.pos()
            self._hold_timer.start()
            event.accept()
            return
        if event.button() == Qt.RightButton:
            if not self._contains_visible_pixel(event.position()):
                event.ignore()
                return
            self._bubble_timer.stop()
            self._right_pressed = True
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if not self._left_pressed:
            super().mouseMoveEvent(event)
            return

        current = event.globalPosition().toPoint()
        distance = (current - self._press_global).manhattanLength()
        if not self._dragging and distance >= self._drag_threshold:
            self._begin_drag()
        if self._dragging:
            destination = current - self._drag_offset
            if destination != self.pos():
                self.move(destination)
                self.drag_moved.emit(QPoint(destination))
            event.accept()
            return
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton and self._left_pressed:
            self._hold_timer.stop()
            if self._dragging:
                final_position = QPoint(self.pos())
                self.drag_finished.emit(final_position)
                self.position_changed.emit(final_position.x(), final_position.y())
                self.pet_event.emit('drag_release', final_position)
            else:
                self.short_clicked.emit()
                self.pet_event.emit('click', None)
                self._bubble_timer.start()
            self._reset_pointer_state()
            event.accept()
            return

        if event.button() == Qt.RightButton and self._right_pressed:
            self._right_pressed = False
            self.right_clicked.emit()
            self.pet_event.emit('right_click', None)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _begin_drag(self) -> None:
        if not self._left_pressed or self._dragging:
            return
        self._bubble_timer.stop()
        self._dragging = True
        self.setCursor(Qt.ClosedHandCursor)
        start = QPoint(self.pos())
        self.drag_started.emit(start)
        self.pet_event.emit('drag_hold', start)

    def _reset_pointer_state(self) -> None:
        self._left_pressed = False
        self._right_pressed = False
        self._dragging = False
        self.setCursor(Qt.OpenHandCursor)

    def _action(self, action_id: str):
        actions = getattr(self._manifest, 'actions', None)
        return actions.get(action_id) if isinstance(actions, Mapping) else None

    @staticmethod
    def _pack_size(manifest) -> tuple[int, int]:
        canvas_size = getattr(manifest, 'canvas_size', None)
        if canvas_size is None:
            raise ValueError('宠物包缺少画布尺寸')
        width, height = int(canvas_size[0]), int(canvas_size[1])
        if width <= 0 or height <= 0 or width > 1024 or height > 1024:
            raise ValueError('宠物包画布尺寸无效')
        return max(48, width), max(48, height)

    @classmethod
    def _validate_pack(cls, pet_id: str, manifest) -> None:
        if not pet_id:
            raise ValueError('宠物标识不能为空')
        cls._pack_size(manifest)
        actions = getattr(manifest, 'actions', None)
        if not isinstance(actions, Mapping) or actions.get('idle') is None:
            raise ValueError('宠物包缺少 idle 动作')

    def _apply_pack(self, pet_id: str, manifest) -> None:
        width, height = self._pack_size(manifest)
        scale = self._scale_percent / 100
        self._pet_id = pet_id
        self._manifest = manifest
        self._appearance_paths = ()
        self._appearance_images = ()
        self._set_fixed_size_if_changed(
            max(48, round(width * scale)),
            max(48, round(height * scale)),
        )
        self.animator.set_pack(pet_id, manifest)
        if not self.play_action('idle'):
            raise RuntimeError('无法启动宠物的 idle 动作')

    def _snapshot_pack(self):
        if self._manifest is None:
            return None
        return (
            self._pet_id,
            self._manifest,
            self.size(),
            self.animator.action_id or 'idle',
            self._appearance_paths,
            tuple(QImage(image) for image in self._appearance_images),
        )

    def _restore_pack_snapshot(self) -> None:
        snapshot = self._switch_snapshot
        if snapshot is None:
            self._clear_pack()
            return
        (
            pet_id,
            manifest,
            size,
            action_id,
            appearance_paths,
            appearance_images,
        ) = snapshot
        self._pet_id = pet_id
        self._manifest = manifest
        self._set_fixed_size_if_changed(size.width(), size.height())
        self._appearance_paths = appearance_paths
        self._appearance_images = tuple(QImage(image) for image in appearance_images)
        self.animator.set_pack(pet_id, manifest)
        if not self.play_action(action_id):
            self.play_action('idle')

    def _clear_pack(self) -> None:
        self._pet_id = ''
        self._manifest = None
        self._frame = None
        self._appearance_paths = ()
        self._appearance_images = ()
        self.animator.stop(clear_frame=True)
        self.update()

    def _start_switch_fade(self, phase: str, end_opacity: float) -> None:
        self._switch_animation.stop()
        self._switch_phase = phase
        self._switch_animation.setStartValue(float(self.windowOpacity()))
        self._switch_animation.setEndValue(float(end_opacity))
        self._switch_animation.start()

    def _switch_animation_finished(self) -> None:
        if self._switch_phase == 'fading_out':
            target = self._switch_target
            if target is None:
                self._restore_pack_snapshot()
                self._start_switch_fade('rollback', 1.0)
                return
            pet_id, manifest = target
            try:
                self._apply_pack(pet_id, manifest)
            except (IndexError, RuntimeError, TypeError, ValueError) as exc:
                self._switch_target = None
                self._restore_pack_snapshot()
                self.pack_switch_failed.emit(pet_id, str(exc))
                self._start_switch_fade('rollback', 1.0)
                return
            self._start_switch_fade('fading_in', 1.0)
            return

        if self._switch_phase == 'fading_in':
            target = self._switch_target
            self._finish_switch()
            if target is not None:
                self.pack_switched.emit(target[0])
            return

        if self._switch_phase == 'rollback':
            self._finish_switch()

    def _complete_switch_immediately(self) -> None:
        self._switch_animation.stop()
        target = self._switch_target
        if self._switch_phase == 'fading_in':
            applied_pet_id = self._pet_id
            self._finish_switch()
            if applied_pet_id:
                self.pack_switched.emit(applied_pet_id)
            return
        if target is None:
            if self._switch_phase == 'rollback':
                self._restore_pack_snapshot()
            self._finish_switch()
            return

        pet_id, manifest = target
        try:
            self._apply_pack(pet_id, manifest)
        except (IndexError, RuntimeError, TypeError, ValueError) as exc:
            self._restore_pack_snapshot()
            self._finish_switch()
            self.pack_switch_failed.emit(pet_id, str(exc))
            return
        self._finish_switch()
        self.pack_switched.emit(pet_id)

    def _finish_switch(self) -> None:
        self._switch_animation.stop()
        self._switch_phase = 'idle'
        self._switch_target = None
        self._switch_snapshot = None
        self.setWindowOpacity(1.0)

    def _has_action(self, action_id: str) -> bool:
        return self._action(action_id) is not None

    def _set_frame(self, image) -> None:
        candidate = (
            QImage(image)
            if isinstance(image, QImage) and not image.isNull()
            else None
        )
        if candidate is None and self._frame is None:
            return
        if (
            candidate is not None
            and self._frame is not None
            and candidate.cacheKey() == self._frame.cacheKey()
        ):
            return
        self._frame = candidate
        self.update()

    def _set_fixed_size_if_changed(self, width: int, height: int) -> bool:
        width, height = int(width), int(height)
        if self.width() == width and self.height() == height:
            return False
        self.setFixedSize(width, height)
        return True

    def _sync_animation_activity(self, *, visible: bool | None = None) -> None:
        if visible is None:
            visible = self.isVisible()
        self.animator.set_surface_visible(bool(visible) and not self._suppressed)

    def _frame_target_rect(self) -> QRectF:
        if not self.has_asset_frame:
            return QRectF(self.rect())
        image_size = self._frame.size()
        scaled = image_size.scaled(self.size(), Qt.KeepAspectRatio)
        left = (self.width() - scaled.width()) / 2
        top = (self.height() - scaled.height()) / 2
        return QRectF(left, top, scaled.width(), scaled.height())

    def _contains_visible_pixel(self, point: QPointF) -> bool:
        if not self.has_asset_frame:
            return self.rect().contains(point.toPoint())
        if self._facing_direction > 0:
            point = QPointF(self.width() - 1 - point.x(), point.y())
        target = self._frame_target_rect()
        if not target.contains(point):
            return False
        x = int((point.x() - target.left()) * self._frame.width() / target.width())
        y = int((point.y() - target.top()) * self._frame.height() / target.height())
        x = max(0, min(x, self._frame.width() - 1))
        y = max(0, min(y, self._frame.height() - 1))
        return self._frame.pixelColor(x, y).alpha() >= 8

    def _paint_fallback(self, painter: QPainter) -> None:
        '''Draw a quiet white-ferret placeholder when a frame cannot load.'''

        scale = min(self.width(), self.height()) / 128
        painter.save()
        painter.scale(scale, scale)
        painter.translate(
            (self.width() / scale - 128) / 2,
            (self.height() / scale - 128) / 2,
        )

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 35))
        painter.drawEllipse(QRectF(24, 101, 82, 13))

        tail = QPainterPath()
        tail.moveTo(87, 88)
        tail.cubicTo(123, 73, 120, 108, 91, 105)
        painter.setPen(QPen(QColor('#171A20'), 14, Qt.SolidLine, Qt.RoundCap))
        painter.drawPath(tail)

        painter.setPen(QPen(QColor('#CBD4E3'), 2))
        painter.setBrush(QColor('#F8FBFF'))
        painter.drawEllipse(QRectF(31, 45, 73, 62))
        painter.drawEllipse(QRectF(22, 20, 70, 68))

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor('#F8FBFF'))
        painter.drawEllipse(QRectF(25, 12, 20, 26))
        painter.drawEllipse(QRectF(68, 12, 20, 26))
        painter.setBrush(QColor('#F2B8C2'))
        painter.drawEllipse(QRectF(31, 18, 9, 13))
        painter.drawEllipse(QRectF(73, 18, 9, 13))

        painter.setBrush(QColor('#171A20'))
        painter.drawEllipse(QRectF(39, 45, 6, 8))
        painter.drawEllipse(QRectF(68, 45, 6, 8))
        painter.drawEllipse(QRectF(54, 58, 7, 5))
        painter.setPen(QPen(QColor('#171A20'), 2, Qt.SolidLine, Qt.RoundCap))
        painter.drawArc(QRectF(49, 58, 9, 9), 210 * 16, 110 * 16)
        painter.drawArc(QRectF(57, 58, 9, 9), 220 * 16, 110 * 16)
        painter.restore()
