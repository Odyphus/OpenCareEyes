'''Stable transparent top-level surface for one desktop companion.'''

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import math

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
from PySide6.QtWidgets import QApplication, QMenu, QWidget

from opencareyes.ui.pet_animator import PetAnimator


@dataclass(frozen=True, slots=True)
class _StableGazeAction:
    action_id: str
    frames: tuple[object, ...]
    loop: bool = False
    static_frame: int = 0


class PetSurface(QWidget):
    '''Render a pet pack and translate pointer gestures into semantic signals.

    The window stays alive while packs and actions change. It never reads the
    break timer and never recreates itself for a frame update, which prevents
    pet animation from disturbing the authoritative rest countdown.
    '''

    short_clicked = Signal()
    bubble_requested = Signal()
    right_clicked = Signal()
    hide_requested = Signal()
    interaction_requested = Signal(str)
    context_menu_changed = Signal(bool)
    drag_started = Signal(QPoint)
    drag_moved = Signal(QPoint)
    drag_finished = Signal(QPoint)
    position_changed = Signal(int, int)
    reset_requested = Signal()
    pet_event = Signal(str, object)
    pack_switched = Signal(str)
    pack_switch_failed = Signal(str, str)
    outfit_switch_failed = Signal(str, str)
    outfit_layer_failed = Signal(str, str)

    def __init__(self, repository=None, parent=None):
        super().__init__(parent)
        self._repository = repository
        self._pet_id = ''
        self._manifest = None
        self._outfit_id = ''
        self._frame: QImage | None = None
        self._appearance_paths: tuple[str, ...] = ()
        self._appearance_images: tuple[QImage, ...] = ()
        self._ambient_paths: tuple[str, ...] = ()
        self._ambient_images: tuple[QImage, ...] = ()
        self._failed_ambient_paths: set[str] = set()
        self._facing_direction = 0
        self._gaze_direction = 'center'
        self._gaze_point = QPointF()
        self._gaze_target = QPointF()
        self._gaze_cell = (2, 2)
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
        self.setToolTip('单击互动，长按拖动；右键可以互动、重置位置或关闭伙伴')
        self.setContextMenuPolicy(Qt.PreventContextMenu)

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

        self._gaze_timer = QTimer(self)
        self._gaze_timer.setTimerType(Qt.PreciseTimer)
        self._gaze_timer.setInterval(50)
        self._gaze_timer.timeout.connect(self._advance_gaze)
        self._preview_active = False
        self._presentation_visible = False
        self._menu_interactions_allowed = True
        self._context_menu = QMenu(self)
        self._context_menu.setAccessibleName('桌面伙伴菜单')
        interaction_menu = self._context_menu.addMenu('和伙伴互动')
        self._context_interactions = {}
        for label, kind, action_id in (
            ('摸摸头', 'click', 'click_reaction'),
            ('玩一会儿', 'item.play', 'play'),
            ('伸个懒腰', 'item.stretch', 'yawn'),
            ('打个招呼', 'item.wave', 'rest_prompt'),
        ):
            action = interaction_menu.addAction(label)
            self._context_interactions[kind] = (action, action_id)
            action.triggered.connect(
                lambda _checked=False, event=kind: self.interaction_requested.emit(event)
            )
        self._context_menu.addAction('重置位置').triggered.connect(
            lambda _checked=False: self.reset_requested.emit()
        )
        self._context_menu.addSeparator()
        self._hide_action = self._context_menu.addAction('关闭桌面伙伴')
        self._hide_action.setToolTip('关闭后可在托盘菜单中重新勾选“显示桌面伙伴”')
        self._hide_action.triggered.connect(lambda _checked=False: self.hide_requested.emit())
        self._context_menu.aboutToShow.connect(lambda: self._set_context_menu_open(True))
        self._context_menu.aboutToHide.connect(lambda: self._set_context_menu_open(False))
        self.apply_theme(None)

    @property
    def pet_id(self) -> str:
        return self._pet_id

    @property
    def action_id(self) -> str:
        return self.animator.action_id

    @property
    def outfit_id(self) -> str:
        return self._outfit_id

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

    def set_outfit(self, outfit_id: str | None) -> bool:
        '''Select one full replacement sprite set without changing the pack.'''

        selected = '' if outfit_id in {None, ''} else str(outfit_id).strip().lower()
        if selected == self._outfit_id:
            return True
        if selected:
            outfits = getattr(self._manifest, 'outfits', None)
            outfit = outfits.get(selected) if isinstance(outfits, Mapping) else None
            actions = getattr(outfit, 'actions', None)
            if not isinstance(actions, Mapping) or actions.get('idle') is None:
                self.outfit_switch_failed.emit(
                    selected,
                    '造型缺少可用的待机动作。',
                )
                return False

        previous = self._outfit_id
        previous_action = self.animator.action_id or 'idle'
        previous_ambient = (
            self._ambient_paths,
            self._ambient_images,
            set(self._failed_ambient_paths),
        )
        self._outfit_id = selected
        self._reload_ambient_layers(force=True)
        self.animator.clear_cache()
        if self.play_action(previous_action, restart=True):
            return True

        self._outfit_id = previous
        (
            self._ambient_paths,
            self._ambient_images,
            self._failed_ambient_paths,
        ) = previous_ambient
        self.animator.clear_cache()
        self.play_action(previous_action, restart=True)
        self.outfit_switch_failed.emit(
            selected,
            '造型画面无法启动，已恢复之前的造型。',
        )
        return False

    def has_action(self, action_id: str) -> bool:
        '''Report an exact current-sprite capability without idle fallback.'''

        return self._exact_action(str(action_id)) is not None

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
        if action_id != 'move':
            self.set_facing_direction(0)
        result = self.animator.play(action_id, action, restart=restart)
        if action_id == 'look_cursor' and not self._reduced_motion and self._exact_action('look_grid'):
            if self._gaze_point != self._gaze_target:
                self._gaze_timer.start()
        else:
            self._gaze_timer.stop()
            self._gaze_point = QPointF()
            self._gaze_cell = (2, 2)
        return result

    def apply_theme(self, snapshot) -> None:
        '''Give the small menu a muted surface, preserving native high contrast.'''

        if bool(getattr(snapshot, 'high_contrast', False)):
            self._context_menu.setStyleSheet('')
            return
        dark = getattr(snapshot, 'resolved', 'dark') == 'dark'
        surface = '#151C29' if dark else '#EEF2F5'
        text = '#F1F5FA' if dark else '#263447'
        border = '#35415A' if dark else '#C7D0DB'
        hover = '#2D3A52' if dark else '#DBE5ED'
        disabled = '#8794A9' if dark else '#7E8A99'
        self._context_menu.setStyleSheet(
            f'QMenu {{ background: {surface}; color: {text}; border: 1px solid {border}; '
            'border-radius: 9px; padding: 5px; } '
            'QMenu::item { padding: 8px 28px 8px 12px; border-radius: 6px; } '
            f'QMenu::item:selected {{ background: {hover}; }} '
            f'QMenu::item:disabled {{ color: {disabled}; }} '
            f'QMenu::separator {{ height: 1px; background: {border}; margin: 5px 8px; }}'
        )

    def set_context_interactions_enabled(self, enabled: bool) -> None:
        self._menu_interactions_allowed = bool(enabled)

    def _show_context_menu(self, global_position: QPoint) -> None:
        self._bubble_timer.stop()
        self._hold_timer.stop()
        self._reset_pointer_state()
        for action, action_id in self._context_interactions.values():
            action.setEnabled(self._menu_interactions_allowed and self.has_action(action_id))
        self._context_menu.popup(global_position)

    def _set_context_menu_open(self, opened: bool) -> None:
        self.setProperty('contextMenuOpen', bool(opened))
        if opened:
            self._gaze_timer.stop()
        self.context_menu_changed.emit(bool(opened))

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Menu or (
            event.key() == Qt.Key_F10 and event.modifiers() & Qt.ShiftModifier
        ):
            self._show_context_menu(self.mapToGlobal(self.rect().center()))
            event.accept()
            return
        super().keyPressEvent(event)

    def set_reduced_motion(self, reduced: bool) -> None:
        reduced = bool(reduced)
        if reduced == self._reduced_motion:
            return
        self._reduced_motion = reduced
        self.animator.set_reduced_motion(self._reduced_motion)
        if self._reduced_motion:
            self._gaze_timer.stop()
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

    def set_gaze_direction(self, direction: str) -> bool:
        '''Select a stable head-gaze frame without mirroring the whole sprite.'''

        normalised = str(direction).strip().lower()
        if normalised not in {
            'left', 'center', 'right', 'up', 'down',
            'up_left', 'up_right', 'down_left', 'down_right',
        }:
            raise ValueError(f'Unsupported gaze direction: {direction!r}')
        changed = normalised != self._gaze_direction
        if self._exact_action('look_grid') is not None:
            cell = {
                'center': (2, 2), 'left': (0, 2), 'right': (4, 2),
                'up': (2, 0), 'down': (2, 4),
                'up_left': (0, 0), 'up_right': (4, 0),
                'down_left': (0, 4), 'down_right': (4, 4),
            }[normalised]
            changed = changed or cell != self._gaze_cell
            self._gaze_cell = cell
            self._gaze_point = QPointF(cell[0] / 2 - 1, cell[1] / 2 - 1)
            self._gaze_target = QPointF(self._gaze_point)
            self._gaze_timer.stop()
        if not changed:
            return False
        self._gaze_direction = normalised
        if self.animator.action_id == 'look_cursor':
            self.play_action('look_cursor', restart=True)
        return True

    def set_gaze_target(self, horizontal: float, vertical: float) -> None:
        '''Follow screen-wide pointer offsets, easing on the surface only.'''

        if not (math.isfinite(horizontal) and math.isfinite(vertical)):
            return
        if self._exact_action('look_grid') is None:
            sector = round(math.atan2(-vertical, horizontal) / (math.pi / 4)) % 8
            direction = ('right', 'up_right', 'up', 'up_left', 'left',
                         'down_left', 'down', 'down_right')[sector]
            self.set_gaze_direction('center' if math.hypot(horizontal, vertical) <= 18 else direction)
            return
        extent = max(180.0, abs(horizontal), abs(vertical))
        self._gaze_target = QPointF(horizontal / extent, vertical / extent)
        if self._reduced_motion or not self.isVisible():
            self._gaze_timer.stop()
            return
        if self.animator.action_id == 'look_cursor' and self._exact_action('look_grid'):
            if self._gaze_point != self._gaze_target:
                self._gaze_timer.start()

    def _advance_gaze(self) -> None:
        if (not self.isVisible() or self._reduced_motion
                or self.animator.action_id != 'look_cursor'
                or bool(self.property('contextMenuOpen'))):
            self._gaze_timer.stop()
            return
        delta = self._gaze_target - self._gaze_point
        if math.hypot(delta.x(), delta.y()) < .012:
            self._gaze_point = QPointF(self._gaze_target)
            self._gaze_timer.stop()
        else:
            self._gaze_point += delta * .38
        cell = list(self._gaze_cell)
        for axis, value in enumerate((self._gaze_point.x(), self._gaze_point.y())):
            candidate = max(0, min(4, round((value + 1) * 2)))
            # Hysteresis prevents a still pointer near a grid boundary from
            # repeatedly switching frames because of one-pixel input noise.
            if candidate != cell[axis] and abs(value - (cell[axis] / 2 - 1)) > .29:
                cell[axis] = candidate
        if tuple(cell) != self._gaze_cell:
            self._gaze_cell = tuple(cell)
            self.animator.play('look_cursor', self._action('look_cursor'), restart=True)

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
        projection_changed = visible != self._presentation_visible
        self._presentation_visible = visible
        if self._preview_active:
            self._preview_timer.stop()
            self._preview_active = False
        if visible:
            if not self.isVisible():
                self.show()
                self.raise_()
                return True
        elif self.isVisible():
            self.hide()
            return True
        return projection_changed

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

    def _reload_ambient_layers(self, *, force: bool = False) -> None:
        paths: tuple[str, ...] = ()
        if self._outfit_id and self._manifest is not None:
            outfits = getattr(self._manifest, 'outfits', None)
            outfit = (
                outfits.get(self._outfit_id)
                if isinstance(outfits, Mapping)
                else None
            )
            layers = getattr(outfit, 'ambient_layers', None)
            if isinstance(layers, Mapping):
                paths = tuple(str(path) for path in layers.values() if path)

        if paths != self._ambient_paths:
            self._ambient_paths = paths
            self._failed_ambient_paths.clear()
            force = True

        images: list[QImage] = []
        if self._repository is not None and self._pet_id:
            for path in self._ambient_paths:
                if path in self._failed_ambient_paths:
                    continue
                image = self._repository.load_frame(self._pet_id, path)
                if isinstance(image, QImage) and not image.isNull():
                    images.append(QImage(image))
        candidate = tuple(images)
        unchanged = tuple(image.cacheKey() for image in candidate) == tuple(
            image.cacheKey() for image in self._ambient_images
        )
        if unchanged and not force:
            return
        self._ambient_images = candidate
        self.update()

    def _on_appearance_resource_ready(
        self,
        pet_id: str,
        resource_path: str,
    ) -> None:
        if str(pet_id) != self._pet_id:
            return
        path = str(resource_path)
        if path in self._ambient_paths:
            self._failed_ambient_paths.discard(path)
            self._reload_ambient_layers()
        if path in self._appearance_paths:
            self._reload_appearance_images()

    def _on_appearance_resource_failed(
        self,
        pet_id: str,
        resource_path: str,
    ) -> None:
        if str(pet_id) != self._pet_id:
            return
        path = str(resource_path)
        if path in self._ambient_paths:
            if path not in self._failed_ambient_paths:
                self._failed_ambient_paths.add(path)
                self._reload_ambient_layers(force=True)
                self.outfit_layer_failed.emit(
                    self._outfit_id,
                    '造型的环境点缀资源无法加载，已隐藏该点缀。',
                )
        elif path in self._appearance_paths:
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

        self._preview_active = True
        if not self.isVisible():
            self.move_to_default()
        self.show()
        self.raise_()
        self._preview_timer.start()

    def _finish_preview(self) -> None:
        self._preview_active = False
        self._preview_timer.stop()
        if not self._presentation_visible:
            self.hide()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._sync_animation_activity()

    def hideEvent(self, event) -> None:
        self._gaze_timer.stop()
        self._context_menu.hide()
        if self._switch_phase != 'idle':
            self._complete_switch_immediately()
        self._preview_active = False
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
        for ambient in self._ambient_images:
            painter.drawImage(QRectF(self.rect()), ambient)
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
            self._reset_pointer_state()
            event.accept()
            return

        if event.button() == Qt.RightButton and self._right_pressed:
            self._right_pressed = False
            self.right_clicked.emit()
            self._show_context_menu(event.globalPosition().toPoint())
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

    def _exact_action(self, action_id: str):
        if self._outfit_id:
            outfits = getattr(self._manifest, 'outfits', None)
            outfit = (
                outfits.get(self._outfit_id)
                if isinstance(outfits, Mapping)
                else None
            )
            actions = getattr(outfit, 'actions', None)
            return actions.get(action_id) if isinstance(actions, Mapping) else None
        actions = getattr(self._manifest, 'actions', None)
        return actions.get(action_id) if isinstance(actions, Mapping) else None

    def _action(self, action_id: str):
        action = self._exact_action(action_id)
        if action is not None and action_id == 'look_cursor':
            grid = self._exact_action('look_grid')
            if grid is not None and len(grid.frames) == 25:
                column, row = self._gaze_cell
                return _StableGazeAction(action_id='look_cursor', frames=(grid.frames[row * 5 + column],))
            turn = self._exact_action(f'look_{self._gaze_direction}')
            if turn is not None:
                return _StableGazeAction(
                    action_id='look_cursor', frames=tuple(turn.frames),
                )
            frames = tuple(getattr(action, 'frames', ()))
            if frames:
                requested = (
                    0 if self._gaze_direction.endswith('left')
                    else 2 if self._gaze_direction.endswith('right') else 1
                )
                frame = frames[min(requested, len(frames) - 1)]
                return _StableGazeAction(
                    action_id=str(getattr(action, 'action_id', action_id)),
                    frames=(frame,),
                )
        if action is not None or not self._outfit_id or action_id == 'idle':
            return action
        return self._exact_action('idle')

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
        self._outfit_id = ''
        self._appearance_paths = ()
        self._appearance_images = ()
        self._ambient_paths = ()
        self._ambient_images = ()
        self._failed_ambient_paths.clear()
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
            self._outfit_id,
            self._appearance_paths,
            tuple(QImage(image) for image in self._appearance_images),
            self._ambient_paths,
            tuple(QImage(image) for image in self._ambient_images),
            set(self._failed_ambient_paths),
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
            outfit_id,
            appearance_paths,
            appearance_images,
            ambient_paths,
            ambient_images,
            failed_ambient_paths,
        ) = snapshot
        self._pet_id = pet_id
        self._manifest = manifest
        self._outfit_id = outfit_id
        self._set_fixed_size_if_changed(size.width(), size.height())
        self._appearance_paths = appearance_paths
        self._appearance_images = tuple(QImage(image) for image in appearance_images)
        self._ambient_paths = ambient_paths
        self._ambient_images = tuple(QImage(image) for image in ambient_images)
        self._failed_ambient_paths = set(failed_ambient_paths)
        self.animator.set_pack(pet_id, manifest)
        if not self.play_action(action_id):
            self.play_action('idle')

    def _clear_pack(self) -> None:
        self._pet_id = ''
        self._manifest = None
        self._outfit_id = ''
        self._frame = None
        self._appearance_paths = ()
        self._appearance_images = ()
        self._ambient_paths = ()
        self._ambient_images = ()
        self._failed_ambient_paths.clear()
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
        return self._exact_action(action_id) is not None

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
