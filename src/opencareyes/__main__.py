"""OpenCareEyes application entry point."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from PySide6.QtCore import (
    QStandardPaths,
    QTimer,
)

from opencareyes.app import OpenCareEyesApp
from opencareyes.application.companion_coordinator import CompanionCoordinator
from opencareyes.application.companion_runtime import CompanionRuntime
from opencareyes.application.context_coordinator import ContextCoordinator
from opencareyes.application.effect_coordinator import EffectCoordinator
from opencareyes.application.holiday_service import HolidayService
from opencareyes.application.hourly_chime_service import HourlyChimeService
from opencareyes.application.note_repository import NoteRepository
from opencareyes.application.pet_asset_repository import PetAssetRepository
from opencareyes.application.pet_pack_registry import PetPackRegistry
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
DEFAULT_PET_ID = "snow_ferret"


def _load_companion(settings, registry):
    """Load the requested pack, preserving a recoverable selection on fallback."""

    active_pet_id = str(getattr(settings, "active_pet_id", DEFAULT_PET_ID))
    recovery_pet_id = str(getattr(settings, "recovery_pet_id", "") or "")
    requested_pet_id = (
        recovery_pet_id if active_pet_id == DEFAULT_PET_ID and recovery_pet_id else active_pet_id
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
            log.exception("The unavailable pet selection could not be persisted")
        return companion, requested_error, True

    if recovery_pet_id:
        try:
            with settings.transaction():
                settings.active_pet_id = requested_pet_id
                settings.recovery_pet_id = ""
        except Exception:
            log.exception("The recovered pet selection could not be persisted")
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
    local_data = Path(QStandardPaths.writableLocation(QStandardPaths.AppLocalDataLocation))
    weather_service = WeatherService()
    holiday_service = HolidayService()
    utility_timer = UtilityTimerService()
    note_repository = NoteRepository(local_data / "notes.json")
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
            preferences.get(companion.state.pet_id, {}) if isinstance(preferences, dict) else {}
        )
        for slot, item_id in selected_preferences.items():
            companion.set_manual_accessory(str(slot), str(item_id))
    elif pet_load_error is not None:
        log.error("The selected bundled pet pack could not be loaded: %s", pet_load_error)
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
        pet_asset_repository=pet_assets,
        weather_service=weather_service,
        utility_timer=utility_timer,
        note_repository=note_repository,
        system_metrics=system_metrics,
    )
    chime_service = HourlyChimeService(app)
    dimmer.operation_failed.connect(controller.operation_failed)
    focus_mode.operation_failed.connect(controller.operation_failed)

    panel = DeferredMainPanel(controller, asset_repository=pet_assets)
    quick_tools = QuickToolsWindow(
        timer_service=utility_timer,
        note_repository=note_repository,
        metrics_service=system_metrics,
        recycle_bin_service=recycle_bin,
    )

    def route_quick_tool(tool_id: str) -> None:
        if tool_id == "wardrobe":
            panel.show_page("宠物图鉴")
            panel.show_and_activate()
            return
        quick_tools.show_tool(tool_id)

    controller.quick_tool_requested.connect(route_quick_tool)
    pet_surface = PetSurface(pet_assets)
    pet_bubble = PetBubble()
    companion_runtime = CompanionRuntime(
        controller,
        companion,
        pet_surface,
        pet_bubble,
        application=app,
        asset_repository=pet_assets,
        pet_registry=pet_registry,
        settings=settings,
        holiday_service=holiday_service,
        chime_service=chime_service,
    )
    if companion is not None:
        pet_surface.set_pack(companion.state.pet_id, companion.manifest)
        app.set_pet_accent(getattr(companion.manifest.visual_theme, "accent", "#65BFA5"))
    session_notifications_available = event_hub.register_window(int(pet_surface.winId()))
    # Keep every top-level reminder surface alive for the application lifetime.
    _break_overlay = BreakOverlay(controller)
    _break_prompt = BreakPrompt(controller)
    tray = TrayIcon(
        controller,
        panel,
        pet_surface,
        companion_runtime=companion_runtime,
    )

    physical_geometry = Win32WindowGeometryBackend(
        ignored_hwnds=companion_runtime.own_window_handles
    )
    logical_geometry = QtLogicalWindowGeometryBackend(physical_geometry)
    window_avoidance = WindowAvoidanceService(
        logical_geometry,
        companion_runtime.current_pet_rect,
        companion_runtime.can_move_for_window_avoidance,
        anchor_rect=companion_runtime.permanent_pet_rect,
        follow_active_monitor=lambda: bool(controller.state.companion.follow_active_monitor),
        avoid_windows=lambda: bool(controller.state.companion.window_avoidance_enabled),
    )
    companion_runtime.attach_window_avoidance(window_avoidance)
    companion_runtime.start()
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
            "已选择的宠物资源包无法加载，已切换到默认白鼬；原选择已保留，资源恢复后会自动重试。"
            if pet_fallback_used
            else "默认白鼬资源包无法加载，暂时使用内置静态占位伙伴。"
        )
        QTimer.singleShot(
            0,
            lambda: controller.operation_failed.emit(
                "pet_pack_load",
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
        companion_runtime.apply_theme(snapshot)
        quick_tools.apply_theme(snapshot)
        for surface in (_break_overlay, _break_prompt):
            surface.apply_theme(snapshot)

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

    def present_first_run() -> None:
        if controller.state.general.onboarding_completed:
            return
        panel.show_and_activate()
        onboarding = OnboardingDialog(controller, panel.widget)
        onboarding.apply_theme(app.theme_snapshot)
        app.theme_snapshot_changed.connect(onboarding.apply_theme)
        try:
            onboarding.exec()
        finally:
            app.theme_snapshot_changed.disconnect(onboarding.apply_theme)
        if controller.state.general.onboarding_completed:
            tray.showMessage(
                "OpenCareEyes 已准备好",
                "鼬鼬会常驻桌面；左键托盘打开伙伴小屋，右键快速控制。",
            )

    QTimer.singleShot(0, present_first_run)

    def on_exit() -> None:
        context_runtime.stop()
        chime_service.stop()
        weather_service.cancel()
        system_metrics.stop()
        companion_runtime.shutdown()
        if not pet_assets.shutdown():
            log.warning("Pet asset worker did not stop before the shutdown timeout")
        # Remove runtime effects through the same boundary used while running,
        # without overwriting the user's saved preferences.
        effect_coordinator.reconcile(effect_coordinator.intent_from_settings(global_pause=True))
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
    log.info("OpenCareEyes application ready")
    ready_marker_path = os.environ.get("OPENCAREYES_READY_FILE")
    if ready_marker_path:
        try:
            Path(ready_marker_path).write_text("OpenCareEyes application ready", encoding="utf-8")
        except OSError:
            log.exception("Application ready marker could not be written")
    exit_code = app.exec()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
