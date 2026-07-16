"""OpenCareEyes application entry point."""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

from PySide6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    QStandardPaths,
    QTimer,
)
from PySide6.QtGui import QCursor

from opencareyes.app import OpenCareEyesApp
from opencareyes.application.companion_coordinator import CompanionCoordinator
from opencareyes.application.context_coordinator import ContextCoordinator
from opencareyes.application.effect_coordinator import EffectCoordinator
from opencareyes.application.holiday_service import HolidayService
from opencareyes.application.hourly_chime_service import HourlyChimeService
from opencareyes.application.note_repository import NoteRepository
from opencareyes.application.pet_asset_repository import PetAssetRepository
from opencareyes.application.pet_pack_registry import PetPackRegistry
from opencareyes.application.status_presenter import StatusPresenter
from opencareyes.application.system_metrics import SystemMetricsService
from opencareyes.application.utility_timer import UtilityTimerService
from opencareyes.application.weather_service import WeatherService
from opencareyes.application.window_avoidance import WindowAvoidanceService
from opencareyes.config.settings import PreferencesRepository
from opencareyes.constants import PETS_DIR
from opencareyes.controller import AppController
from opencareyes.core.break_reminder import BreakReminder
from opencareyes.core.display_worker import QueuedBlueLightFilter
from opencareyes.core.focus_mode import FocusMode
from opencareyes.core.scheduler import Scheduler
from opencareyes.core.screen_dimmer import ScreenDimmer
from opencareyes.diagnostics import configure_logging
from opencareyes.platform.context_sensor import ContextSensor
from opencareyes.platform.hotkeys import HotkeyManager
from opencareyes.platform.recycle_bin import RecycleBinService
from opencareyes.platform.window_geometry import (
    QtLogicalWindowGeometryBackend,
    ScreenRect,
    Win32WindowGeometryBackend,
)
from opencareyes.platform.windows_event_hub import WindowsEventHub
from opencareyes.ui.break_overlay import BreakOverlay
from opencareyes.ui.break_prompt import BreakPrompt
from opencareyes.ui.main_panel import DeferredMainPanel
from opencareyes.ui.onboarding import OnboardingDialog
from opencareyes.ui.pet_bubble import PetBubble
from opencareyes.ui.pet_surface import PetSurface
from opencareyes.ui.quick_tools import QuickToolsWindow
from opencareyes.ui.tray_icon import TrayIcon


log = logging.getLogger(__name__)
DEFAULT_PET_ID = 'snow_ferret'


def _load_companion(settings, registry):
    '''Load the requested pack, preserving a recoverable selection on fallback.'''

    active_pet_id = str(getattr(settings, 'active_pet_id', DEFAULT_PET_ID))
    recovery_pet_id = str(getattr(settings, 'recovery_pet_id', '') or '')
    requested_pet_id = (
        recovery_pet_id
        if active_pet_id == DEFAULT_PET_ID and recovery_pet_id
        else active_pet_id
    )

    try:
        companion = CompanionCoordinator(
            registry,
            active_pet_id=requested_pet_id,
        )
    except Exception as requested_error:
        if requested_pet_id == DEFAULT_PET_ID:
            return None, requested_error, False
        try:
            companion = CompanionCoordinator(
                registry,
                active_pet_id=DEFAULT_PET_ID,
            )
        except Exception as default_error:
            return None, default_error, False
        try:
            with settings.transaction():
                settings.active_pet_id = DEFAULT_PET_ID
                settings.recovery_pet_id = requested_pet_id
        except Exception:
            log.exception('The unavailable pet selection could not be persisted')
        return companion, requested_error, True

    if recovery_pet_id:
        try:
            with settings.transaction():
                settings.active_pet_id = requested_pet_id
                settings.recovery_pet_id = ''
        except Exception:
            log.exception('The recovered pet selection could not be persisted')
    return companion, None, False


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    app = OpenCareEyesApp(sys.argv)
    if not app.ensure_single_instance():
        log.info("Another instance is already running; activation requested")
        return

    # Only the primary instance opens the rotating log. On Windows a second
    # process cannot append to the file while the primary process owns it.
    configure_logging()

    settings = PreferencesRepository()
    local_data = Path(
        QStandardPaths.writableLocation(QStandardPaths.AppLocalDataLocation)
    )
    weather_service = WeatherService()
    holiday_service = HolidayService()
    utility_timer = UtilityTimerService()
    note_repository = NoteRepository(local_data / 'notes.json')
    system_metrics = SystemMetricsService()
    recycle_bin = RecycleBinService()
    pet_registry = PetPackRegistry(PETS_DIR)
    pet_assets = PetAssetRepository(pet_registry, app)
    companion, pet_load_error, pet_fallback_used = _load_companion(
        settings,
        pet_registry,
    )
    if companion is not None:
        pet_assets.preload_manifest(companion.manifest)
        preferences = settings.pet_preferences
        selected_preferences = (
            preferences.get(companion.state.pet_id, {})
            if isinstance(preferences, dict)
            else {}
        )
        for slot, item_id in selected_preferences.items():
            companion.set_manual_accessory(str(slot), str(item_id))
    elif pet_load_error is not None:
        log.error('The selected bundled pet pack could not be loaded: %s', pet_load_error)
    event_hub = WindowsEventHub.shared()
    event_hub.install(app)
    blue_filter = QueuedBlueLightFilter(auto_watch_screens=False)
    dimmer = ScreenDimmer(watch_screen_events=False)
    break_reminder = BreakReminder()
    focus_mode = FocusMode(watch_screen_events=False)
    scheduler = Scheduler(settings=settings)
    hotkeys = HotkeyManager(event_hub=event_hub)
    context_sensor = ContextSensor(event_hub=event_hub)
    effect_coordinator = EffectCoordinator(
        settings,
        blue_filter=blue_filter,
        dimmer=dimmer,
        break_reminder=break_reminder,
        focus_mode=focus_mode,
    )
    context_runtime = ContextCoordinator(
        settings,
        context_sensor,
        effect_coordinator,
    )

    controller = AppController(
        settings=settings,
        blue_filter=blue_filter,
        dimmer=dimmer,
        break_reminder=break_reminder,
        focus_mode=focus_mode,
        scheduler=scheduler,
        hotkeys=hotkeys,
        effect_coordinator=effect_coordinator,
        companion=companion,
        weather_service=weather_service,
        utility_timer=utility_timer,
        note_repository=note_repository,
        system_metrics=system_metrics,
    )
    chime_service = HourlyChimeService(app)
    dimmer.operation_failed.connect(controller.operation_failed)
    focus_mode.operation_failed.connect(controller.operation_failed)

    panel = DeferredMainPanel(controller)
    quick_tools = QuickToolsWindow(
        timer_service=utility_timer,
        note_repository=note_repository,
        metrics_service=system_metrics,
        recycle_bin_service=recycle_bin,
    )

    def route_quick_tool(tool_id: str) -> None:
        if tool_id == 'wardrobe':
            panel.show_page('宠物图鉴')
            panel.show_and_activate()
            return
        quick_tools.show_tool(tool_id)

    controller.quick_tool_requested.connect(route_quick_tool)
    pet_surface = PetSurface(pet_assets)
    pet_bubble = PetBubble()
    if companion is not None:
        pet_surface.set_pack(companion.state.pet_id, companion.manifest)
        app.set_pet_accent(
            getattr(companion.manifest.visual_theme, 'accent', '#65BFA5')
        )
    session_notifications_available = event_hub.register_window(
        int(pet_surface.winId())
    )
    # Keep every top-level reminder surface alive for the application lifetime.
    _break_overlay = BreakOverlay(controller)
    _break_prompt = BreakPrompt(controller)
    tray = TrayIcon(controller, panel, pet_surface)

    autonomous_motion = QPropertyAnimation(pet_surface, b'pos')
    autonomous_motion.setEasingCurve(QEasingCurve.InOutSine)
    autonomous_end = QTimer()
    autonomous_end.setSingleShot(True)
    autonomous_timer = QTimer()
    autonomous_timer.setSingleShot(True)
    cursor_timer = QTimer()
    cursor_timer.setInterval(500)
    last_cursor_position = QCursor.pos()
    last_cursor_motion = time.monotonic()
    last_cursor_reaction = 0.0

    def own_window_handles() -> frozenset[int]:
        handles: set[int] = set()
        for widget in app.topLevelWidgets():
            if not widget.isVisible():
                continue
            try:
                handles.add(int(widget.winId()))
            except (RuntimeError, TypeError, ValueError):
                continue
        return frozenset(handles)

    physical_geometry = Win32WindowGeometryBackend(
        ignored_hwnds=own_window_handles
    )
    logical_geometry = QtLogicalWindowGeometryBackend(physical_geometry)

    def current_pet_rect() -> ScreenRect:
        geometry = pet_surface.frameGeometry()
        return ScreenRect(
            geometry.x(),
            geometry.y(),
            geometry.x() + geometry.width(),
            geometry.y() + geometry.height(),
        )

    def permanent_pet_rect() -> ScreenRect:
        anchor = controller.state.companion.anchor
        if anchor.edge == 'free' and anchor.x is not None and anchor.y is not None:
            return ScreenRect(
                int(anchor.x),
                int(anchor.y),
                int(anchor.x) + pet_surface.width(),
                int(anchor.y) + pet_surface.height(),
            )
        current = pet_surface.frameGeometry()
        screen = app.screenAt(current.center()) or app.primaryScreen()
        if screen is None:
            return current_pet_rect()
        area = screen.availableGeometry()
        offset = max(0, int(anchor.offset))
        left = area.x() + offset
        right = area.x() + area.width() - pet_surface.width() - offset
        top = area.y() + offset
        bottom = area.y() + area.height() - pet_surface.height() - offset
        x = left if anchor.edge.endswith('left') else right
        y = top if anchor.edge.startswith('top') else bottom
        return ScreenRect(x, y, x + pet_surface.width(), y + pet_surface.height())

    def companion_can_move() -> bool:
        state = controller.state
        return (
            bool(state.companion.visible)
            and state.breaks.phase != 'resting'
            and not pet_surface.is_dragging
            and not pet_bubble.isVisible()
            and not bool(pet_surface.property('autonomousMoving'))
        )

    window_avoidance = WindowAvoidanceService(
        logical_geometry,
        current_pet_rect,
        companion_can_move,
        anchor_rect=permanent_pet_rect,
        follow_active_monitor=lambda: bool(
            controller.state.companion.follow_active_monitor
        ),
        avoid_windows=lambda: bool(
            controller.state.companion.window_avoidance_enabled
        ),
    )

    def apply_temporary_pet_move(request) -> None:
        pet_surface.setProperty('serviceTransientPlacement', True)
        pet_surface.move(*request.position)

    def restore_permanent_pet_anchor() -> None:
        pet_surface.setProperty('serviceTransientPlacement', False)
        anchor = permanent_pet_rect()
        pet_surface.move(anchor.left, anchor.top)

    window_avoidance.move_requested.connect(apply_temporary_pet_move)
    window_avoidance.restore_requested.connect(restore_permanent_pet_anchor)

    def persist_pet_position(x: int, y: int) -> None:
        pet_surface.setProperty('serviceTransientPlacement', False)
        controller.set_pet_anchor('free', 0, x, y)

    pet_surface.position_changed.connect(persist_pet_position)

    def reset_pet_anchor() -> None:
        pet_surface.setProperty('serviceTransientPlacement', False)
        controller.set_pet_anchor('bottom_right', 24)
        controller.reset_pet_position()

    pet_surface.reset_requested.connect(reset_pet_anchor)

    def dispatch_pet_event(kind: str, payload=None) -> bool:
        if companion is None:
            return False
        semantic = {
            'drag_hold': 'drag.hold',
            'drag_release': 'drag.release',
        }.get(str(kind), str(kind))
        if semantic in {'click', 'right_click', 'drag.hold', 'drag.release'}:
            autonomous_motion.stop()
            autonomous_end.stop()
            pet_surface.setProperty('autonomousMoving', False)
        safe_payload = payload if isinstance(payload, dict) else {}
        try:
            changed = companion.dispatch_kind(semantic, safe_payload)
        except (TypeError, ValueError):
            log.exception('Invalid semantic pet event was rejected')
            return False
        if changed:
            pet_surface.play_action(
                companion.current_action.action_id,
                restart=True,
            )
            controller.refresh_companion_presentation(force=True)
        return changed

    pet_surface.pet_event.connect(dispatch_pet_event)
    controller.pet_event_requested.connect(dispatch_pet_event)

    pet_surface.pack_switched.connect(
        lambda _pet_id: controller.refresh_companion_presentation(force=True)
    )

    def handle_pack_switch_failure(_pet_id: str, _detail: str) -> None:
        if companion is not None and pet_surface.pet_id:
            active = str(companion.state.pet_id)
            if active != pet_surface.pet_id:
                controller.set_active_pet(pet_surface.pet_id)
        controller.operation_failed.emit(
            'pet_pack_surface',
            '新伙伴的画面无法加载，已恢复切换前的伙伴。',
        )

    pet_surface.pack_switch_failed.connect(handle_pack_switch_failure)

    def handle_hourly_chime(hour: int, may_play_sound: bool) -> None:
        if not dispatch_pet_event('reminder.hourly', {'hour': int(hour)}):
            return
        if pet_surface.isVisible():
            pet_bubble.set_status(f'{hour} 点啦', '活动一下肩颈，再继续专注吧。')
            pet_bubble.show_for(pet_surface)
        if not may_play_sound or companion is None:
            return
        sound_path = companion.manifest.sound_rules.get('reminder.hourly')
        if not sound_path:
            return
        try:
            import winsound

            resolved = pet_registry.resolve_resource(
                companion.state.pet_id,
                sound_path,
            )
            winsound.PlaySound(
                str(resolved),
                winsound.SND_ASYNC | winsound.SND_FILENAME | winsound.SND_NODEFAULT,
            )
        except (ImportError, OSError, RuntimeError, ValueError):
            log.warning('Companion chime could not be played')

    chime_service.chime.connect(handle_hourly_chime)

    def finish_pet_action(action_id: str) -> None:
        if companion is None or not companion.complete_action(action_id):
            return
        pet_surface.play_action(companion.current_action.action_id)
        controller.refresh_companion_presentation(force=True)

    pet_surface.animator.animation_finished.connect(finish_pet_action)

    def finish_autonomous_action() -> None:
        if companion is None:
            return
        action_id = companion.state.behavior.action_id
        if companion.complete_action(action_id):
            pet_surface.play_action(companion.current_action.action_id)
            controller.refresh_companion_presentation(force=True)
        pet_surface.setProperty('autonomousMoving', False)

    autonomous_motion.finished.connect(finish_autonomous_action)
    autonomous_end.timeout.connect(finish_autonomous_action)

    def schedule_autonomous_action() -> None:
        if companion is None or not pet_surface.isVisible():
            autonomous_timer.stop()
            return
        activity = int(getattr(companion.manifest.personality, 'activity', 50))
        autonomous_timer.start(max(9000, 26000 - activity * 170))

    def run_autonomous_action() -> None:
        if (
            companion is None
            or pet_surface.is_dragging
            or not pet_surface.isVisible()
            or pet_bubble.isVisible()
            or bool(pet_surface.property('serviceTransientPlacement'))
        ):
            schedule_autonomous_action()
            return
        if companion.start_autonomous_action():
            action_id = companion.current_action.action_id
            pet_surface.play_action(action_id, restart=True)
            controller.refresh_state()
            if action_id == 'move':
                screen = pet_surface.screen()
                if screen is not None:
                    area = screen.availableGeometry()
                    start = pet_surface.pos()
                    room_right = area.right() - pet_surface.width() - start.x()
                    room_left = start.x() - area.left()
                    distance = min(180, max(room_right, room_left))
                    direction = 1 if room_right >= room_left else -1
                    end = pet_surface.pos()
                    end.setX(start.x() + direction * max(0, distance))
                    pet_surface.set_facing_direction(direction)
                    autonomous_motion.setStartValue(start)
                    autonomous_motion.setEndValue(end)
                    speed = max(
                        1.0,
                        float(companion.manifest.personality.walk_speed),
                    )
                    autonomous_motion.setDuration(
                        max(900, round(distance / speed * 1000))
                    )
                    pet_surface.setProperty('autonomousMoving', True)
                    autonomous_motion.start()
            elif action_id == 'sleep':
                autonomous_end.start(6000)
        schedule_autonomous_action()

    autonomous_timer.timeout.connect(run_autonomous_action)

    def probe_cursor() -> None:
        nonlocal last_cursor_position, last_cursor_motion, last_cursor_reaction
        if companion is None or not pet_surface.isVisible() or pet_surface.is_dragging:
            return
        now = time.monotonic()
        position = QCursor.pos()
        if position != last_cursor_position:
            last_cursor_position = position
            last_cursor_motion = now
            if companion.state.behavior.event_kind == 'cursor.still':
                companion.clear_event('cursor.still')
                pet_surface.play_action(companion.current_action.action_id)
                controller.refresh_companion_presentation(force=True)
        if bool(pet_surface.property('autonomousMoving')):
            if cursor_timer.interval() != 500:
                cursor_timer.setInterval(500)
            return
        centre = pet_surface.geometry().center()
        distance = (position - centre).manhattanLength()
        if distance <= 180:
            if cursor_timer.interval() != 100:
                cursor_timer.setInterval(100)
            pet_surface.face_towards_cursor(position)
            if now - last_cursor_reaction >= 2.0:
                last_cursor_reaction = now
                dispatch_pet_event('cursor.near')
        elif (
            now - last_cursor_motion >= 45
            and companion.state.behavior.event_kind == 'autonomous.idle'
        ):
            if cursor_timer.interval() != 500:
                cursor_timer.setInterval(500)
            dispatch_pet_event('cursor.still')
        else:
            if cursor_timer.interval() != 500:
                cursor_timer.setInterval(500)

    cursor_timer.timeout.connect(probe_cursor)

    def toggle_pet_bubble() -> None:
        pet_bubble.toggle_for(pet_surface)
        if companion is not None:
            companion.set_bubble_visible(pet_bubble.isVisible())
            controller.refresh_companion_presentation(force=True)

    pet_surface.bubble_requested.connect(toggle_pet_bubble)

    def dismiss_pet_bubble() -> None:
        if companion is not None:
            companion.set_bubble_visible(False)
            controller.refresh_companion_presentation(force=True)

    pet_bubble.dismissed.connect(dismiss_pet_bubble)

    def handle_pet_tool(tool_id: str) -> None:
        if tool_id == 'rest':
            controller.start_break_now()
            pet_bubble.hide()
            return
        mapped = {'note': 'notes', 'status': 'system'}.get(tool_id, tool_id)
        controller.show_quick_tool(mapped)

    pet_bubble.tool_requested.connect(handle_pet_tool)

    def offer_pet_item(item_id: str) -> None:
        if controller.offer_pet_item(item_id):
            pet_bubble.hide()

    pet_bubble.item_requested.connect(offer_pet_item)
    controller.break_tick.connect(pet_bubble.set_break_countdown)

    pet_positioned = False
    last_break_semantic = None
    last_appearance_conditions = None

    def render_companion_presentation(presentation) -> None:
        if companion is not None and presentation.pet_id != pet_surface.pet_id:
            pet_assets.preload_manifest(companion.manifest)
            if not pet_surface.set_pack(presentation.pet_id, companion.manifest):
                return
            visual_theme = getattr(companion.manifest, 'visual_theme', None)
            app.set_pet_accent(getattr(visual_theme, 'accent', '#65BFA5'))

        reduced = presentation.motion_profile == 'reduced' or not app.motion_enabled
        pet_surface.set_reduced_motion(reduced)
        pet_surface.set_scale_percent(presentation.scale_percent)
        pet_surface.set_appearance(presentation.appearance)
        pet_surface.set_suppressed(bool(presentation.suppressed_by))
        pet_surface.set_presentation_visible(presentation.visible)

        if presentation.visible:
            if not cursor_timer.isActive():
                cursor_timer.start()
            if not autonomous_timer.isActive():
                schedule_autonomous_action()
        else:
            pet_bubble.hide()
            cursor_timer.stop()
            autonomous_timer.stop()
            autonomous_end.stop()
            autonomous_motion.stop()
            pet_surface.setProperty('autonomousMoving', False)

        if pet_surface.action_id != presentation.action_id:
            pet_surface.play_action(presentation.action_id)

    def render_companion(state) -> None:
        nonlocal pet_positioned, last_break_semantic, last_appearance_conditions
        companion_state = state.companion

        if companion is not None:
            conditions: list[str] = []
            app_id = str(getattr(state.context, 'foreground_app_id', '')).lower()
            custom_prop = next(
                (
                    str(rule.get('prop_id', ''))
                    for rule in settings.app_prop_rules
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
            for holiday in holiday_service.current_events(
                pack=settings.holiday_pack
            ):
                conditions.append(holiday.appearance_key)
            condition_tuple = tuple(conditions)
            appearance_signature = (companion_state.pet_id, condition_tuple)
            if appearance_signature != last_appearance_conditions:
                last_appearance_conditions = appearance_signature
                companion.apply_appearance_conditions(condition_tuple)
                controller.refresh_companion_presentation(force=True)
        chime_service.configure(
            bool(state.quick_tools.hourly_chime_enabled),
            bool(companion_state.sound_enabled),
            state.quick_tools.quiet_hours_start,
            state.quick_tools.quiet_hours_end,
        )
        chime_service.set_allowed(
            bool(companion_state.visible)
            and state.context.session == 'active'
            and not state.context.fullscreen
            and state.breaks.phase != 'resting'
        )

        anchor = companion_state.anchor
        if (
            anchor.edge == 'free'
            and anchor.x is not None
            and anchor.y is not None
            and not pet_surface.is_dragging
            and not bool(pet_surface.property('autonomousMoving'))
            and not bool(pet_surface.property('serviceTransientPlacement'))
        ):
            pet_surface.move(int(anchor.x), int(anchor.y))
            pet_positioned = True
        elif not pet_positioned:
            pet_surface.move_to_default()
            pet_positioned = True

        break_semantic = (
            state.breaks.phase,
            state.break_prompt.stage,
            state.breaks.force_break,
        )
        if break_semantic != last_break_semantic:
            last_break_semantic = break_semantic
            behavior_changed = companion is not None and companion.sync_break_behavior(
                state.breaks.phase,
                state.break_prompt.stage,
            )
            if behavior_changed:
                pet_surface.play_action(
                    companion.current_action.action_id,
                    restart=True,
                )
                controller.refresh_companion_presentation(force=True)
            if state.breaks.phase == 'resting':
                pet_bubble.hide()
            elif state.break_prompt.stage not in {'none', 'hidden'}:
                if companion_state.visible and not state.breaks.force_break:
                    pet_bubble.set_status('该休息一下了', '看看远处，让眼睛放松。')
                    pet_bubble.show_for(pet_surface)

        status = StatusPresenter.project(state)
        pet_bubble.set_status(status.headline, status.detail)
        pet_bubble.set_break_countdown(
            state.breaks.remaining,
            state.breaks.total,
        )
        pet_bubble.set_quick_actions(state.quick_tools.quick_actions)

    controller.state_changed.connect(render_companion)
    controller.companion_presentation_changed.connect(
        render_companion_presentation
    )
    app.motion_changed.connect(
        lambda enabled: pet_surface.set_reduced_motion(not enabled)
    )
    render_companion(controller.state)
    render_companion_presentation(controller.companion_presentation)

    if not session_notifications_available:
        log.warning("Windows session notifications are unavailable")
        QTimer.singleShot(
            0,
            lambda: controller.operation_failed.emit(
                "session_notifications_unavailable",
                "锁屏状态检测暂时不可用；应用仍会继续检测全屏和空闲状态。",
            ),
        )

    if pet_load_error is not None:
        message = (
            '已选择的宠物资源包无法加载，已切换到默认白鼬；'
            '原选择已保留，资源恢复后会自动重试。'
            if pet_fallback_used
            else '默认白鼬资源包无法加载，暂时使用内置静态占位伙伴。'
        )
        QTimer.singleShot(
            0,
            lambda: controller.operation_failed.emit(
                'pet_pack_load',
                message,
            ),
        )

    def refresh_display_topology(*_args) -> None:
        blue_filter.refresh_screens()
        dimmer.refresh_screens()
        focus_mode.refresh_screens()

    def refresh_after_session_change(inactive: bool) -> None:
        if not inactive:
            refresh_display_topology()

    event_hub.display_changed.connect(refresh_display_topology)
    event_hub.clock_changed.connect(scheduler.reschedule)
    event_hub.clock_changed.connect(chime_service.reschedule)
    event_hub.session_locked.connect(refresh_after_session_change)
    event_hub.system_suspended.connect(refresh_after_session_change)

    def apply_state_theme(state) -> None:
        app.apply_theme(state.general.theme)
        app.apply_motion_mode(state.general.motion_mode)

    def apply_window_theme(snapshot) -> None:
        pet_bubble.set_theme(snapshot)
        quick_tools.apply_theme(snapshot)
        for surface in (_break_overlay, _break_prompt):
            surface.setProperty('resolvedTheme', snapshot.resolved)
            surface.setProperty('highContrast', snapshot.high_contrast)
            surface.update()

    controller.state_changed.connect(apply_state_theme)
    app.theme_snapshot_changed.connect(apply_window_theme)
    app.activation_requested.connect(panel.show_and_activate)
    tray.show()
    app.apply_theme(controller.state.general.theme)
    app.apply_motion_mode(controller.state.general.motion_mode)
    apply_window_theme(app.theme_snapshot)
    # Prime the context sensor before restoring persisted effects. Starting
    # inside a full-screen presentation must never flash a focus/rest overlay.
    context_runtime.start()
    controller.attach_context_runtime(context_runtime)
    controller.restore()
    chime_service.start()
    window_avoidance.start()

    def present_first_run() -> None:
        if controller.state.general.onboarding_completed:
            return
        panel.show_and_activate()
        onboarding = OnboardingDialog(controller, panel.widget)
        onboarding.exec()
        if controller.state.general.onboarding_completed:
            tray.showMessage(
                "OpenCareEyes 已准备好",
                "鼬鼬会常驻桌面；左键托盘打开伙伴小屋，右键快速控制。",
            )

    QTimer.singleShot(0, present_first_run)

    def on_exit() -> None:
        context_runtime.stop()
        window_avoidance.stop(restore=False)
        chime_service.stop()
        weather_service.cancel()
        system_metrics.stop()
        if not pet_assets.shutdown():
            log.warning('Pet asset worker did not stop before the shutdown timeout')
        # Remove runtime effects through the same boundary used while running,
        # without overwriting the user's saved preferences.
        effect_coordinator.reconcile(
            effect_coordinator.intent_from_settings(global_pause=True)
        )
        scheduler.stop()
        hotkeys.unregister_all()
        event_hub.shutdown(app)
        if not blue_filter.shutdown():
            log.warning("Display worker did not stop before the shutdown timeout")
        try:
            settings.sync_checked()
        except Exception:
            log.exception("Settings could not be synced during shutdown")
        app.cleanup()

    app.aboutToQuit.connect(on_exit)
    exit_code = app.exec()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
