'''Runtime boundary for the desktop companion and its lightweight activity.'''

from __future__ import annotations

import logging
import math
import time
from collections.abc import Callable

from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, QTimer
from PySide6.QtGui import QCursor

from opencareyes.application.status_presenter import StatusPresenter
from opencareyes.platform.window_geometry import ScreenRect


log = logging.getLogger(__name__)


class CompanionRuntime:
    '''Own companion UI wiring, autonomous activity, and window avoidance.'''

    def __init__(
        self,
        controller,
        companion,
        surface,
        bubble,
        *,
        application=None,
        asset_repository=None,
        pet_registry=None,
        settings=None,
        chime_service=None,
        status_projector: Callable = StatusPresenter.project,
        monotonic: Callable[[], float] = time.monotonic,
        cursor_position: Callable[[], QPoint] = QCursor.pos,
    ):
        self._controller = controller
        self._companion = companion
        self._surface = surface
        self._bubble = bubble
        self._application = application
        self._asset_repository = asset_repository
        self._pet_registry = pet_registry
        self._settings = settings
        self._chime_service = chime_service
        self._status_projector = status_projector
        self._monotonic = monotonic
        self._cursor_position = cursor_position

        self._last_break_semantic = None
        self._last_cursor_position = None
        self._last_cursor_motion = self._monotonic()
        self._last_cursor_reaction = 0.0
        self._pet_positioned = False
        self._motion_reduced = False
        self._started = False
        self._shutdown = False

        self._autonomous_motion = None
        self._autonomous_end = None
        self._interaction_end = None
        self._interaction_kind = ''
        self._autonomous_timer = None
        self._cursor_timer = None
        self._window_avoidance = None
        self._window_avoidance_running = False

        attach_surface = getattr(controller, 'attach_companion_surface', None)
        if callable(attach_surface):
            attach_surface(surface)

        bubble.start_due_requested.connect(controller.start_due_break)
        bubble.snooze_requested.connect(controller.snooze_break)
        bubble.skip_requested.connect(controller.skip_break)
        controller.break_tick.connect(bubble.set_break_countdown)

    def attach_window_avoidance(self, service) -> None:
        '''Attach the platform service without leaking its callbacks into main.'''

        if self._window_avoidance is service:
            return
        if self._window_avoidance is not None:
            raise RuntimeError('window avoidance is already attached')
        self._window_avoidance = service
        service.move_requested.connect(self._apply_temporary_move)
        service.restore_requested.connect(self.restore_permanent_anchor)

    def start(self) -> None:
        if self._started or self._shutdown:
            return
        if self._application is None:
            raise RuntimeError('an application instance is required to start the runtime')

        self._started = True
        self._build_timers()
        self._wire_surface_events()
        self._controller.state_changed.connect(self.sync_state)
        self._controller.companion_presentation_changed.connect(
            self.sync_presentation
        )
        self._application.motion_changed.connect(self._apply_motion_preference)
        if self._chime_service is not None:
            self._chime_service.chime.connect(self._handle_hourly_chime)

        self.sync_presentation(self._controller.companion_presentation)
        self.sync_state(self._controller.state)
        self._start_window_avoidance()

    def sync_state(self, state) -> None:
        if self._shutdown:
            return
        set_menu_enabled = getattr(self._surface, 'set_context_interactions_enabled', None)
        if callable(set_menu_enabled):
            set_menu_enabled(not (
                state.companion.suppressed_by or state.global_pause.active
                or state.breaks.phase == 'resting'
                or state.break_prompt.stage not in {'none', 'hidden'}
            ))
        break_visual_suppressed = bool(
            state.global_pause.active
            or not state.companion.visible
            or state.companion.suppressed_by
        )
        visual_phase = (
            'working' if break_visual_suppressed else state.breaks.phase
        )
        visual_prompt_stage = (
            'none' if break_visual_suppressed else state.break_prompt.stage
        )
        break_semantic = (
            visual_phase,
            visual_prompt_stage,
            state.breaks.force_break,
            break_visual_suppressed,
        )
        if break_semantic != self._last_break_semantic:
            self._last_break_semantic = break_semantic
            behavior_changed = (
                self._companion is not None
                and self._companion.sync_break_behavior(
                    visual_phase,
                    visual_prompt_stage,
                )
            )
            if behavior_changed:
                self._surface.play_action(
                    self._companion.current_action.action_id,
                    restart=True,
                )
                self._controller.refresh_companion_presentation(force=True)
            self._sync_break_prompt(state, break_visual_suppressed)

        status = self._status_projector(state)
        if not self._bubble.is_rest_prompt_active:
            self._bubble.set_status(status.headline, status.detail)
        self._bubble.set_break_countdown(
            state.breaks.remaining,
            state.breaks.total,
        )
        self._bubble.set_quick_actions(state.quick_tools.quick_actions)

        if self._started:
            self._sync_chime(state)
            self._sync_anchor()
        self._sync_focus_behavior(state)

    def _sync_focus_behavior(self, state) -> None:
        if self._companion is None:
            return
        focusing = bool(
            state.focus.enabled and state.companion.visible
            and not state.global_pause.active and not state.companion.suppressed_by
        )
        has_action = getattr(self._surface, 'has_action', None)
        if focusing and callable(has_action) and has_action('read'):
            self.dispatch_pet_event('application.focus')
        elif self._companion.state.behavior.event_kind == 'application.focus':
            if self._companion.clear_event('application.focus'):
                self._surface.play_action(self._companion.current_action.action_id)
                self._controller.refresh_companion_presentation(force=True)

    def sync_presentation(self, presentation) -> None:
        if self._shutdown:
            return
        if self._companion is not None and presentation.pet_id != self._surface.pet_id:
            if self._asset_repository is not None:
                self._asset_repository.preload_manifest(self._companion.manifest)
            pack_applied = self._surface.set_pack(
                presentation.pet_id,
                self._companion.manifest,
            )
            if pack_applied:
                visual_theme = getattr(
                    self._companion.manifest,
                    'visual_theme',
                    None,
                )
                if self._application is not None:
                    self._application.set_pet_accent(
                        getattr(visual_theme, 'accent', '#65BFA5')
                    )

        self._surface.set_scale_percent(presentation.scale_percent)
        set_outfit = getattr(self._surface, 'set_outfit', None)
        if callable(set_outfit):
            set_outfit(getattr(presentation, 'outfit_id', ''))
        set_capabilities = getattr(self._bubble, 'set_interaction_capabilities', None)
        has_action = getattr(self._surface, 'has_action', None)
        if callable(set_capabilities) and callable(has_action):
            set_capabilities(has_action)
        self._surface.set_appearance(presentation.appearance)
        if self._started:
            self._sync_anchor()
        self._surface.set_suppressed(bool(presentation.suppressed_by))
        self._surface.set_presentation_visible(presentation.visible)

        app_motion_enabled = bool(
            getattr(self._application, 'motion_enabled', True)
        )
        reduced = (
            presentation.motion_profile == 'reduced'
            or not app_motion_enabled
        )
        self.set_motion_reduced(reduced)

        if not presentation.visible:
            self._bubble.hide()
        if self._surface.action_id != presentation.action_id:
            self._surface.play_action(presentation.action_id)
        self._refresh_timer_state()

    def apply_theme(self, snapshot) -> None:
        surface_theme = getattr(self._surface, 'apply_theme', None)
        if callable(surface_theme):
            surface_theme(snapshot)
        apply_theme = getattr(self._bubble, 'apply_theme', None)
        if callable(apply_theme):
            apply_theme(snapshot)
        else:
            self._bubble.set_theme(snapshot)

    def show_bubble(self, *, focusable: bool = False) -> bool:
        '''The retired status card has no product entry point.

        The rest-due prompt still uses its dedicated reminder path.
        '''

        return False

    def set_motion_reduced(self, reduced: bool) -> None:
        reduced = bool(reduced)
        changed = reduced != self._motion_reduced
        self._motion_reduced = reduced
        self._surface.set_reduced_motion(reduced)
        if hasattr(self._surface, 'setProperty'):
            self._surface.setProperty('motionReduced', reduced)
        if not changed:
            return
        if changed and reduced and self._started:
            self._stop_autonomous_action(complete=True)
            if self._cursor_timer is not None:
                self._cursor_timer.stop()
            self._stop_window_avoidance(restore=False)
            if not self._surface.is_dragging:
                self.restore_permanent_anchor()
        self._refresh_timer_state()

    def shutdown(self) -> None:
        if self._shutdown:
            return
        self._shutdown = True
        self._last_break_semantic = None
        self._stop_window_avoidance(restore=False)
        self._stop_all_timers()
        if self._interaction_end is not None:
            self._interaction_end.stop()
        self._bubble.clear_rest_prompt()
        self._bubble.hide()

    def own_window_handles(self) -> frozenset[int]:
        handles: set[int] = set()
        if self._application is None:
            return frozenset()
        for widget in self._application.topLevelWidgets():
            if not widget.isVisible():
                continue
            try:
                handles.add(int(widget.winId()))
            except (RuntimeError, TypeError, ValueError):
                continue
        return frozenset(handles)

    def current_pet_rect(self) -> ScreenRect:
        geometry = self._surface.frameGeometry()
        return ScreenRect(
            geometry.x(),
            geometry.y(),
            geometry.x() + geometry.width(),
            geometry.y() + geometry.height(),
        )

    def permanent_pet_rect(self) -> ScreenRect:
        anchor = self._controller.state.companion.anchor
        if anchor.edge == 'free' and anchor.x is not None and anchor.y is not None:
            width = self._surface.width()
            height = self._surface.height()
            x = int(anchor.x)
            y = int(anchor.y)
            screen = self._screen_for_point(
                QPoint(x + width // 2, y + height // 2)
            )
            if screen is not None:
                area = screen.availableGeometry()
                x = max(
                    area.left(),
                    min(x, area.left() + max(0, area.width() - width)),
                )
                y = max(
                    area.top(),
                    min(y, area.top() + max(0, area.height() - height)),
                )
            return ScreenRect(
                x,
                y,
                x + width,
                y + height,
            )
        current = self._surface.frameGeometry()
        screen = self._screen_for_point(current.center())
        if screen is None:
            return self.current_pet_rect()
        area = screen.availableGeometry()
        offset = max(0, int(anchor.offset))
        left = area.x() + offset
        right = area.x() + area.width() - self._surface.width() - offset
        top = area.y() + offset
        bottom = area.y() + area.height() - self._surface.height() - offset
        x = left if anchor.edge.endswith('left') else right
        y = top if anchor.edge.startswith('top') else bottom
        return ScreenRect(x, y, x + self._surface.width(), y + self._surface.height())

    def _screen_for_point(self, point: QPoint):
        if self._application is None:
            return None
        screen_at = getattr(self._application, 'screenAt', None)
        primary_screen = getattr(self._application, 'primaryScreen', None)
        screen = screen_at(point) if callable(screen_at) else None
        if screen is None and callable(primary_screen):
            screen = primary_screen()
        return screen

    def can_move_for_window_avoidance(self) -> bool:
        state = self._controller.state
        return (
            bool(state.companion.visible)
            and self._surface.isVisible()
            and state.breaks.phase != 'resting'
            and not self._motion_reduced
            and not self._surface.is_dragging
            and not self._bubble.isVisible()
            and not bool(self._surface.property('contextMenuOpen'))
            and not bool(self._surface.property('autonomousMoving'))
        )

    def restore_permanent_anchor(self) -> None:
        if not self._started or self._surface.is_dragging:
            return
        self._surface.setProperty('serviceTransientPlacement', False)
        anchor = self.permanent_pet_rect()
        self._surface.move(anchor.left, anchor.top)
        self._pet_positioned = True

    def refresh_display_topology(self, *_args) -> None:
        '''Recover the persisted anchor after monitor or DPI topology changes.'''

        if self._shutdown or not self._started or self._surface.is_dragging:
            return
        self._surface.setProperty('serviceTransientPlacement', False)
        self._pet_positioned = False
        self._sync_anchor()
        reposition = getattr(self._bubble, 'reposition', None)
        if self._bubble.isVisible() and callable(reposition):
            reposition(self._surface)

    def dispatch_pet_event(self, kind: str, payload=None) -> bool:
        if self._companion is None:
            return False
        semantic = {
            'drag_hold': 'drag.hold',
            'drag_release': 'drag.release',
        }.get(str(kind), str(kind))
        if semantic in {'click', 'right_click', 'drag.hold', 'drag.release'} or semantic.startswith('item.'):
            self._stop_autonomous_action(complete=False)
            if self._interaction_end is not None:
                self._interaction_end.stop()
        safe_payload = payload if isinstance(payload, dict) else {}
        try:
            changed = self._companion.dispatch_kind(semantic, safe_payload)
        except (TypeError, ValueError):
            log.exception('Invalid semantic pet event was rejected')
            return False
        if changed:
            self._surface.play_action(
                self._companion.current_action.action_id,
                restart=True,
            )
            self._controller.refresh_companion_presentation(force=True)
            action = self._companion.current_action
            manual = semantic in {'click', 'right_click', 'drag.release'} or semantic.startswith('item.')
            if (manual and self._interaction_end is not None
                    and (action.loop or self._motion_reduced)):
                duration = sum(frame.duration_ms for frame in action.frames)
                self._interaction_kind = semantic
                self._interaction_end.start(max(300, min(5000, duration)))
        return changed

    def _build_timers(self) -> None:
        self._autonomous_motion = QPropertyAnimation(
            self._surface,
            b'pos',
            self._surface,
        )
        # Constant travel speed matches the authored walk-cycle cadence.
        self._autonomous_motion.setEasingCurve(QEasingCurve.Linear)
        self._autonomous_motion.finished.connect(self._finish_autonomous_action)

        self._autonomous_end = QTimer(self._surface)
        self._autonomous_end.setSingleShot(True)
        self._autonomous_end.timeout.connect(self._finish_autonomous_action)

        self._interaction_end = QTimer(self._surface)
        self._interaction_end.setSingleShot(True)
        self._interaction_end.timeout.connect(self._finish_interaction)

        self._autonomous_timer = QTimer(self._surface)
        self._autonomous_timer.setSingleShot(True)
        self._autonomous_timer.timeout.connect(self._run_autonomous_action)

        self._cursor_timer = QTimer(self._surface)
        self._cursor_timer.setInterval(50)
        self._cursor_timer.timeout.connect(self._probe_cursor)
        self._last_cursor_position = self._cursor_position()

    def _wire_surface_events(self) -> None:
        self._surface.position_changed.connect(self._persist_pet_position)
        self._surface.reset_requested.connect(self._reset_pet_anchor)
        self._surface.pet_event.connect(self.dispatch_pet_event)
        hide_requested = getattr(self._surface, 'hide_requested', None)
        if hide_requested is not None:
            hide_requested.connect(self._hide_pet)
        interaction_requested = getattr(self._surface, 'interaction_requested', None)
        if interaction_requested is not None:
            interaction_requested.connect(self.interact)
        context_menu_changed = getattr(self._surface, 'context_menu_changed', None)
        if context_menu_changed is not None:
            context_menu_changed.connect(self._context_menu_changed)
        self._controller.pet_event_requested.connect(self.dispatch_pet_event)
        self._surface.pack_switched.connect(
            lambda _pet_id: self._controller.refresh_companion_presentation(
                force=True
            )
        )
        self._surface.pack_switch_failed.connect(self._handle_pack_switch_failure)
        outfit_failed = getattr(self._surface, 'outfit_switch_failed', None)
        if outfit_failed is not None:
            outfit_failed.connect(self._handle_outfit_switch_failure)
        layer_failed = getattr(self._surface, 'outfit_layer_failed', None)
        if layer_failed is not None:
            layer_failed.connect(self._handle_outfit_layer_failure)
        self._surface.animator.animation_finished.connect(self._finish_pet_action)
        self._bubble.dismissed.connect(self._dismiss_pet_bubble)
        self._bubble.tool_requested.connect(self._handle_pet_tool)
        interaction = getattr(self._bubble, 'interaction_requested', None)
        if interaction is not None:
            interaction.connect(self.interact)

    def interact(self, kind: str) -> bool:
        """Explicit play obeys the same reminder and safety arbitration as clicks."""

        if kind not in {'click', 'item.play', 'item.stretch', 'item.wave'}:
            return False
        if self._shutdown or not self._surface.isVisible():
            return False
        state = self._controller.state
        if (state.companion.suppressed_by or state.global_pause.active
                or state.breaks.phase == 'resting' or self._bubble.is_rest_prompt_active):
            return False
        action_id = {
            'click': 'click_reaction', 'item.play': 'play',
            'item.stretch': 'yawn', 'item.wave': 'rest_prompt',
        }[kind]
        has_action = getattr(self._surface, 'has_action', None)
        if callable(has_action) and not has_action(action_id):
            return False
        changed = self.dispatch_pet_event(kind)
        if changed:
            self._bubble.hide()
            self._dismiss_pet_bubble()
        return changed

    def _apply_temporary_move(self, request) -> None:
        self._surface.setProperty('serviceTransientPlacement', True)
        self._surface.move(*request.position)

    def _persist_pet_position(self, x: int, y: int) -> None:
        self._surface.setProperty('serviceTransientPlacement', False)
        self._controller.set_pet_anchor('free', 0, x, y)

    def _reset_pet_anchor(self) -> None:
        self._surface.setProperty('serviceTransientPlacement', False)
        self._controller.reset_pet_position()

    def _hide_pet(self) -> None:
        if not self._shutdown:
            self._controller.set_companion_enabled(False)

    def _context_menu_changed(self, opened: bool) -> None:
        if self._shutdown:
            return
        if opened:
            self._bubble.hide()
            self._dismiss_pet_bubble()
            self._stop_all_timers()
            self._stop_autonomous_action(complete=True)
            self._stop_window_avoidance(restore=False)
        else:
            self._refresh_timer_state()

    def _handle_pack_switch_failure(self, _pet_id: str, _detail: str) -> None:
        if self._companion is not None and self._surface.pet_id:
            active = str(self._companion.state.pet_id)
            if active != self._surface.pet_id:
                self._controller.set_active_pet(self._surface.pet_id)
        self._controller.operation_failed.emit(
            'pet_pack_surface',
            '新伙伴的画面无法加载，已恢复切换前的伙伴。',
        )

    def _handle_outfit_switch_failure(
        self,
        outfit_id: str,
        detail: str,
    ) -> None:
        reporter = getattr(
            self._controller,
            'report_wardrobe_surface_failure',
            None,
        )
        if callable(reporter):
            reporter(str(outfit_id), str(detail))
            return
        self._controller.operation_failed.emit(
            'pet_outfit_surface',
            str(detail),
        )

    def _handle_outfit_layer_failure(
        self,
        _outfit_id: str,
        detail: str,
    ) -> None:
        self._controller.operation_failed.emit(
            'pet_outfit_layer',
            str(detail),
        )

    def _finish_pet_action(self, action_id: str) -> None:
        if (self._companion is not None and action_id == 'look_cursor'
                and self._companion.state.behavior.event_kind == 'cursor.near'):
            return
        if self._companion is None or not self._companion.complete_action(action_id):
            return
        if self._interaction_end is not None:
            self._interaction_end.stop()
        self._surface.play_action(self._companion.current_action.action_id)
        self._controller.refresh_companion_presentation(force=True)
        self._sync_focus_behavior(self._controller.state)

    def _finish_interaction(self) -> None:
        if (not self._shutdown and self._companion is not None
                and self._companion.state.behavior.event_kind == self._interaction_kind):
            self._finish_pet_action(self._companion.current_action.action_id)

    def _finish_autonomous_action(self) -> None:
        if self._companion is not None:
            action_id = self._companion.state.behavior.action_id
            if self._companion.complete_action(action_id):
                self._surface.play_action(self._companion.current_action.action_id)
                self._controller.refresh_companion_presentation(force=True)
        if hasattr(self._surface, 'setProperty'):
            self._surface.setProperty('autonomousMoving', False)
        self._sync_focus_behavior(self._controller.state)

    def _schedule_autonomous_action(self) -> None:
        if self._autonomous_timer is None:
            return
        if (
            self._companion is None
            or not self._surface.isVisible()
            or bool(self._surface.property('contextMenuOpen'))
            or self._motion_reduced
        ):
            self._autonomous_timer.stop()
            return
        activity = int(getattr(self._companion.manifest.personality, 'activity', 50))
        self._autonomous_timer.start(max(9000, 26000 - activity * 170))

    def _run_autonomous_action(self) -> None:
        state = self._controller.state
        if (
            self._companion is None
            or self._surface.is_dragging
            or not self._surface.isVisible()
            or self._bubble.isVisible()
            or bool(self._surface.property('contextMenuOpen'))
            or self._motion_reduced
            or state.breaks.phase == 'resting'
            or state.focus.enabled
            or state.break_prompt.stage not in {'none', 'hidden'}
            or bool(self._surface.property('serviceTransientPlacement'))
        ):
            self._schedule_autonomous_action()
            return
        if self._companion.start_autonomous_action():
            action_id = self._companion.current_action.action_id
            has_action = getattr(self._surface, 'has_action', None)
            if (
                action_id == 'move'
                and callable(has_action)
                and not has_action('move')
            ):
                if self._companion.complete_action(action_id):
                    self._surface.play_action(
                        self._companion.current_action.action_id
                    )
                    self._controller.refresh_companion_presentation(force=True)
                self._schedule_autonomous_action()
                return
            self._surface.play_action(action_id, restart=True)
            self._controller.refresh_companion_presentation(force=True)
            if action_id == 'move':
                screen = self._surface.screen()
                if screen is not None:
                    area = screen.availableGeometry()
                    start = self._surface.pos()
                    room_right = area.right() - self._surface.width() - start.x()
                    room_left = start.x() - area.left()
                    distance = min(180, max(room_right, room_left))
                    direction = 1 if room_right >= room_left else -1
                    if distance > 0:
                        end = QPoint(start)
                        end.setX(start.x() + direction * distance)
                        self._surface.set_facing_direction(direction)
                        self._autonomous_motion.setStartValue(start)
                        self._autonomous_motion.setEndValue(end)
                        speed = max(
                            1.0,
                            float(self._companion.manifest.personality.walk_speed),
                        )
                        self._autonomous_motion.setDuration(
                            max(900, round(distance / speed * 1000))
                        )
                        self._surface.setProperty('autonomousMoving', True)
                        self._autonomous_motion.start()
                    else:
                        self._finish_autonomous_action()
            elif action_id == 'sleep':
                self._autonomous_end.start(6000)
        self._schedule_autonomous_action()

    def _probe_cursor(self) -> None:
        if (
            self._companion is None
            or not self._surface.isVisible()
            or self._surface.is_dragging
            or bool(self._surface.property('contextMenuOpen'))
            or self._motion_reduced
        ):
            self._set_cursor_interval(500)
            return
        now = self._monotonic()
        position = self._cursor_position()
        if position != self._last_cursor_position:
            self._last_cursor_position = position
            self._last_cursor_motion = now
            if self._companion.state.behavior.event_kind == 'cursor.still':
                self._companion.clear_event('cursor.still')
                self._surface.play_action(self._companion.current_action.action_id)
                self._controller.refresh_companion_presentation(force=True)
        if bool(self._surface.property('autonomousMoving')):
            self._set_cursor_interval(500)
            return
        state = self._controller.state
        if (state.breaks.phase == 'resting' or state.focus.enabled
                or state.global_pause.active or state.companion.suppressed_by
                or state.break_prompt.stage not in {'none', 'hidden'}
                or self._companion.current_action.action_id == 'sleep'):
            self._set_cursor_interval(500)
            return
        self._set_cursor_interval(50)
        offset = position - self._surface.geometry().center()
        gaze = self._cursor_gaze_direction(offset.x(), offset.y())
        set_target = getattr(self._surface, 'set_gaze_target', None)
        if callable(set_target):
            set_target(offset.x(), offset.y())
        else:
            set_gaze = getattr(self._surface, 'set_gaze_direction', None)
            if callable(set_gaze):
                set_gaze(gaze)
        # Enter tracking once. Re-dispatching the same event used to restart
        # the action every two seconds; a fixed cursor now holds its pose.
        if self._companion.state.behavior.event_kind != 'cursor.near':
            self._last_cursor_reaction = now
            self.dispatch_pet_event('cursor.near', {'gaze': gaze})

    @staticmethod
    def _cursor_gaze_direction(horizontal: int, vertical: int) -> str:
        if math.hypot(horizontal, vertical) <= 18:
            return 'center'
        # Eight readable screen directions; a small central dead zone avoids
        # rapid left/right flips as the pointer crosses the character's nose.
        sector = round(math.atan2(-vertical, horizontal) / (math.pi / 4)) % 8
        return ('right', 'up_right', 'up', 'up_left', 'left',
                'down_left', 'down', 'down_right')[sector]

    def _set_cursor_interval(self, interval: int) -> None:
        if self._cursor_timer is not None and self._cursor_timer.interval() != interval:
            self._cursor_timer.setInterval(interval)

    def _stop_autonomous_action(self, *, complete: bool) -> None:
        if self._autonomous_timer is not None:
            self._autonomous_timer.stop()
        if self._autonomous_end is not None:
            self._autonomous_end.stop()
        if self._autonomous_motion is not None:
            self._autonomous_motion.stop()
        if hasattr(self._surface, 'setProperty'):
            self._surface.setProperty('autonomousMoving', False)
        if complete and self._companion is not None:
            event_kind = str(self._companion.state.behavior.event_kind)
            if event_kind.startswith('autonomous.'):
                action_id = self._companion.state.behavior.action_id
                if self._companion.complete_action(action_id):
                    self._surface.play_action(
                        self._companion.current_action.action_id
                    )
                    self._controller.refresh_companion_presentation(force=True)

    def _stop_all_timers(self) -> None:
        if self._cursor_timer is not None:
            self._cursor_timer.stop()
        self._stop_autonomous_action(complete=False)

    def _refresh_timer_state(self) -> None:
        if not self._started or self._cursor_timer is None:
            return
        if not self._surface.isVisible():
            self._stop_all_timers()
            self._stop_window_avoidance()
            return
        if bool(self._surface.property('contextMenuOpen')):
            self._stop_all_timers()
            return
        if self._motion_reduced:
            self._cursor_timer.stop()
            self._stop_autonomous_action(complete=True)
            self._stop_window_avoidance()
            return
        self._start_window_avoidance()
        if not self._cursor_timer.isActive():
            self._cursor_timer.start()
        if not self._autonomous_timer.isActive():
            self._schedule_autonomous_action()

    def _toggle_pet_bubble(self) -> None:
        return

    def _start_window_avoidance(self) -> None:
        if self._window_avoidance is None or self._window_avoidance_running:
            return
        self._window_avoidance.start()
        self._window_avoidance_running = True

    def _stop_window_avoidance(self, *, restore: bool = True) -> None:
        if self._window_avoidance is None or not self._window_avoidance_running:
            return
        self._window_avoidance.stop(restore=restore)
        self._window_avoidance_running = False

    def _dismiss_pet_bubble(self) -> None:
        if self._companion is not None:
            self._companion.set_bubble_visible(False)
            self._controller.refresh_companion_presentation(force=True)

    def _handle_pet_tool(self, tool_id: str) -> None:
        if tool_id == 'rest':
            self._controller.start_break_now()
            self._bubble.hide()
            return
        mapped = {'note': 'notes', 'status': 'system'}.get(tool_id, tool_id)
        self._controller.show_quick_tool(mapped)

    def _handle_hourly_chime(self, hour: int, may_play_sound: bool) -> None:
        if not self.dispatch_pet_event('reminder.hourly', {'hour': int(hour)}):
            return
        if (
            not may_play_sound
            or self._companion is None
            or self._pet_registry is None
        ):
            return
        sound_path = self._companion.manifest.sound_rules.get('reminder.hourly')
        if not sound_path:
            return
        try:
            import winsound

            resolved = self._pet_registry.resolve_resource(
                self._companion.state.pet_id,
                sound_path,
            )
            winsound.PlaySound(
                str(resolved),
                winsound.SND_ASYNC
                | winsound.SND_FILENAME
                | winsound.SND_NODEFAULT,
            )
        except (ImportError, OSError, RuntimeError, ValueError):
            log.warning('Companion chime could not be played')

    def _sync_chime(self, state) -> None:
        if self._chime_service is None:
            return
        self._chime_service.configure(
            bool(state.quick_tools.hourly_chime_enabled),
            bool(state.companion.sound_enabled),
            state.quick_tools.quiet_hours_start,
            state.quick_tools.quiet_hours_end,
        )
        self._chime_service.set_allowed(
            bool(state.companion.visible)
            and state.context.session == 'active'
            and not state.context.fullscreen
            and state.breaks.phase != 'resting'
        )

    def _sync_anchor(self) -> None:
        if (
            self._surface.is_dragging
            or bool(self._surface.property('autonomousMoving'))
            or bool(self._surface.property('serviceTransientPlacement'))
        ):
            return
        anchor = self.permanent_pet_rect()
        if (
            not self._pet_positioned
            or self._surface.pos() != QPoint(anchor.left, anchor.top)
        ):
            self._surface.move(anchor.left, anchor.top)
        self._pet_positioned = True

    def _apply_motion_preference(self, enabled: bool) -> None:
        self.set_motion_reduced(not bool(enabled))

    def _sync_break_prompt(self, state, suppressed: bool = False) -> None:
        if suppressed:
            self._bubble.clear_rest_prompt()
            return
        if state.breaks.phase == 'resting':
            self._bubble.clear_rest_prompt()
            self._bubble.hide()
            return
        if state.break_prompt.stage not in {'none', 'hidden'}:
            if state.companion.visible and not state.breaks.force_break:
                self._bubble.show_rest_prompt(
                    self._surface,
                    title='该休息一下眼睛了',
                    detail='看看远处，让眼睛放松一下。',
                )
            return
        self._bubble.clear_rest_prompt()
