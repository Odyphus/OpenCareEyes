'''Runtime boundary for the desktop companion and its lightweight activity.'''

from __future__ import annotations

import logging
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
        holiday_service=None,
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
        self._holiday_service = holiday_service
        self._chime_service = chime_service
        self._status_projector = status_projector
        self._monotonic = monotonic
        self._cursor_position = cursor_position

        self._last_break_semantic = None
        self._last_appearance_conditions = None
        self._last_cursor_position = None
        self._last_cursor_motion = self._monotonic()
        self._last_cursor_reaction = 0.0
        self._pet_positioned = False
        self._motion_reduced = False
        self._started = False
        self._shutdown = False

        self._autonomous_motion = None
        self._autonomous_end = None
        self._autonomous_timer = None
        self._cursor_timer = None
        self._window_avoidance = None
        self._window_avoidance_running = False

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
            self._sync_appearance_and_chime(state)
            self._sync_anchor(state)

    def sync_presentation(self, presentation) -> None:
        if self._shutdown:
            return
        if self._companion is not None and presentation.pet_id != self._surface.pet_id:
            if self._asset_repository is not None:
                self._asset_repository.preload_manifest(self._companion.manifest)
            if not self._surface.set_pack(
                presentation.pet_id,
                self._companion.manifest,
            ):
                return
            visual_theme = getattr(self._companion.manifest, 'visual_theme', None)
            if self._application is not None:
                self._application.set_pet_accent(
                    getattr(visual_theme, 'accent', '#65BFA5')
                )

        self._surface.set_scale_percent(presentation.scale_percent)
        self._surface.set_appearance(presentation.appearance)
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
        apply_theme = getattr(self._bubble, 'apply_theme', None)
        if callable(apply_theme):
            apply_theme(snapshot)
        else:
            self._bubble.set_theme(snapshot)

    def show_bubble(self, *, focusable: bool = False) -> bool:
        '''Show the companion bubble through an explicit input-mode boundary.'''

        if self._shutdown or not self._surface.isVisible():
            return False
        self._bubble.show_for(self._surface, focusable=bool(focusable))
        if self._companion is not None:
            self._companion.set_bubble_visible(True)
            self._controller.refresh_companion_presentation(force=True)
        return True

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
            self._stop_window_avoidance()
            if not self._surface.is_dragging:
                self.restore_permanent_anchor()
        self._refresh_timer_state()

    def shutdown(self) -> None:
        if self._shutdown:
            return
        self._shutdown = True
        self._last_break_semantic = None
        self._stop_window_avoidance()
        self._stop_all_timers()
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
            return ScreenRect(
                int(anchor.x),
                int(anchor.y),
                int(anchor.x) + self._surface.width(),
                int(anchor.y) + self._surface.height(),
            )
        current = self._surface.frameGeometry()
        screen = None
        if self._application is not None:
            screen = (
                self._application.screenAt(current.center())
                or self._application.primaryScreen()
            )
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

    def can_move_for_window_avoidance(self) -> bool:
        state = self._controller.state
        return (
            bool(state.companion.visible)
            and state.breaks.phase != 'resting'
            and not self._motion_reduced
            and not self._surface.is_dragging
            and not self._bubble.isVisible()
            and not bool(self._surface.property('autonomousMoving'))
        )

    def restore_permanent_anchor(self) -> None:
        if not self._started or self._surface.is_dragging:
            return
        self._surface.setProperty('serviceTransientPlacement', False)
        anchor = self.permanent_pet_rect()
        self._surface.move(anchor.left, anchor.top)

    def dispatch_pet_event(self, kind: str, payload=None) -> bool:
        if self._companion is None:
            return False
        semantic = {
            'drag_hold': 'drag.hold',
            'drag_release': 'drag.release',
        }.get(str(kind), str(kind))
        if semantic in {'click', 'right_click', 'drag.hold', 'drag.release'}:
            self._stop_autonomous_action(complete=False)
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
        return changed

    def _build_timers(self) -> None:
        self._autonomous_motion = QPropertyAnimation(
            self._surface,
            b'pos',
            self._surface,
        )
        self._autonomous_motion.setEasingCurve(QEasingCurve.InOutSine)
        self._autonomous_motion.finished.connect(self._finish_autonomous_action)

        self._autonomous_end = QTimer(self._surface)
        self._autonomous_end.setSingleShot(True)
        self._autonomous_end.timeout.connect(self._finish_autonomous_action)

        self._autonomous_timer = QTimer(self._surface)
        self._autonomous_timer.setSingleShot(True)
        self._autonomous_timer.timeout.connect(self._run_autonomous_action)

        self._cursor_timer = QTimer(self._surface)
        self._cursor_timer.setInterval(500)
        self._cursor_timer.timeout.connect(self._probe_cursor)
        self._last_cursor_position = self._cursor_position()

    def _wire_surface_events(self) -> None:
        self._surface.position_changed.connect(self._persist_pet_position)
        self._surface.reset_requested.connect(self._reset_pet_anchor)
        self._surface.pet_event.connect(self.dispatch_pet_event)
        self._controller.pet_event_requested.connect(self.dispatch_pet_event)
        self._surface.pack_switched.connect(
            lambda _pet_id: self._controller.refresh_companion_presentation(
                force=True
            )
        )
        self._surface.pack_switch_failed.connect(self._handle_pack_switch_failure)
        self._surface.animator.animation_finished.connect(self._finish_pet_action)
        self._surface.bubble_requested.connect(self._toggle_pet_bubble)
        self._bubble.dismissed.connect(self._dismiss_pet_bubble)
        self._bubble.tool_requested.connect(self._handle_pet_tool)
        self._bubble.item_requested.connect(self._offer_pet_item)

    def _apply_temporary_move(self, request) -> None:
        self._surface.setProperty('serviceTransientPlacement', True)
        self._surface.move(*request.position)

    def _persist_pet_position(self, x: int, y: int) -> None:
        self._surface.setProperty('serviceTransientPlacement', False)
        self._controller.set_pet_anchor('free', 0, x, y)

    def _reset_pet_anchor(self) -> None:
        self._surface.setProperty('serviceTransientPlacement', False)
        self._controller.set_pet_anchor('bottom_right', 24)
        self._controller.reset_pet_position()

    def _handle_pack_switch_failure(self, _pet_id: str, _detail: str) -> None:
        if self._companion is not None and self._surface.pet_id:
            active = str(self._companion.state.pet_id)
            if active != self._surface.pet_id:
                self._controller.set_active_pet(self._surface.pet_id)
        self._controller.operation_failed.emit(
            'pet_pack_surface',
            '新伙伴的画面无法加载，已恢复切换前的伙伴。',
        )

    def _finish_pet_action(self, action_id: str) -> None:
        if self._companion is None or not self._companion.complete_action(action_id):
            return
        self._surface.play_action(self._companion.current_action.action_id)
        self._controller.refresh_companion_presentation(force=True)

    def _finish_autonomous_action(self) -> None:
        if self._companion is not None:
            action_id = self._companion.state.behavior.action_id
            if self._companion.complete_action(action_id):
                self._surface.play_action(self._companion.current_action.action_id)
                self._controller.refresh_companion_presentation(force=True)
        if hasattr(self._surface, 'setProperty'):
            self._surface.setProperty('autonomousMoving', False)

    def _schedule_autonomous_action(self) -> None:
        if self._autonomous_timer is None:
            return
        if (
            self._companion is None
            or not self._surface.isVisible()
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
            or self._motion_reduced
            or state.breaks.phase == 'resting'
            or state.break_prompt.stage not in {'none', 'hidden'}
            or bool(self._surface.property('serviceTransientPlacement'))
        ):
            self._schedule_autonomous_action()
            return
        if self._companion.start_autonomous_action():
            action_id = self._companion.current_action.action_id
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
        distance = (position - self._surface.geometry().center()).manhattanLength()
        if distance <= 180:
            self._set_cursor_interval(100)
            self._surface.face_towards_cursor(position)
            if now - self._last_cursor_reaction >= 2.0:
                self._last_cursor_reaction = now
                self.dispatch_pet_event('cursor.near')
        elif (
            now - self._last_cursor_motion >= 45
            and self._companion.state.behavior.event_kind == 'autonomous.idle'
        ):
            self._set_cursor_interval(500)
            self.dispatch_pet_event('cursor.still')
        else:
            self._set_cursor_interval(500)

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
        self._bubble.toggle_for(self._surface, focusable=False)
        if self._companion is not None:
            self._companion.set_bubble_visible(self._bubble.isVisible())
            self._controller.refresh_companion_presentation(force=True)

    def _start_window_avoidance(self) -> None:
        if self._window_avoidance is None or self._window_avoidance_running:
            return
        self._window_avoidance.start()
        self._window_avoidance_running = True

    def _stop_window_avoidance(self) -> None:
        if self._window_avoidance is None or not self._window_avoidance_running:
            return
        self._window_avoidance.stop(restore=False)
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

    def _offer_pet_item(self, item_id: str) -> None:
        if self._controller.offer_pet_item(item_id):
            self._bubble.hide()

    def _handle_hourly_chime(self, hour: int, may_play_sound: bool) -> None:
        if not self.dispatch_pet_event('reminder.hourly', {'hour': int(hour)}):
            return
        if self._surface.isVisible():
            self._bubble.set_status(
                f'{hour} 点啦',
                '活动一下肩颈，再继续专注吧。',
            )
            self._bubble.show_for(self._surface)
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

    def _sync_appearance_and_chime(self, state) -> None:
        if self._companion is not None:
            conditions: list[str] = []
            app_id = str(getattr(state.context, 'foreground_app_id', '')).lower()
            rules = getattr(self._settings, 'app_prop_rules', ())
            custom_prop = next(
                (
                    str(rule.get('prop_id', ''))
                    for rule in rules
                    if str(rule.get('app_id', '')).lower() == app_id
                ),
                '',
            )
            if custom_prop:
                conditions.append(f'application.{custom_prop}')
            elif app_id in {'winword.exe', 'wps.exe', 'wpscloudsvr.exe'}:
                conditions.append('application.writing')
            elif app_id in {'calculator.exe', 'calc.exe'}:
                conditions.append('application.calculator')
            elif app_id in {
                'kicad.exe',
                'pcbnew.exe',
                'altiumdesigner.exe',
                'easyeda.exe',
            }:
                conditions.append('application.eda')
            if state.weather.status in {'ready', 'stale'}:
                conditions.append(f'weather.{state.weather.condition}')
            if self._holiday_service is not None:
                holiday_pack = getattr(self._settings, 'holiday_pack', 'default')
                for holiday in self._holiday_service.current_events(
                    pack=holiday_pack
                ):
                    conditions.append(holiday.appearance_key)
            condition_tuple = tuple(conditions)
            signature = (state.companion.pet_id, condition_tuple)
            if signature != self._last_appearance_conditions:
                self._last_appearance_conditions = signature
                self._companion.apply_appearance_conditions(condition_tuple)
                self._controller.refresh_companion_presentation(force=True)

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

    def _sync_anchor(self, state) -> None:
        anchor = state.companion.anchor
        if (
            anchor.edge == 'free'
            and anchor.x is not None
            and anchor.y is not None
            and not self._surface.is_dragging
            and not bool(self._surface.property('autonomousMoving'))
            and not bool(self._surface.property('serviceTransientPlacement'))
        ):
            self._surface.move(int(anchor.x), int(anchor.y))
            self._pet_positioned = True
        elif not self._pet_positioned:
            self._surface.move_to_default()
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
