"""OpenCareEyes application entry point."""

from __future__ import annotations

import logging
import sys

from PySide6.QtCore import QTimer

from opencareyes.app import OpenCareEyesApp
from opencareyes.application.context_coordinator import ContextCoordinator
from opencareyes.application.effect_coordinator import EffectCoordinator
from opencareyes.config.settings import PreferencesRepository
from opencareyes.controller import AppController
from opencareyes.core.break_reminder import BreakReminder
from opencareyes.core.display_worker import QueuedBlueLightFilter
from opencareyes.core.focus_mode import FocusMode
from opencareyes.core.scheduler import Scheduler
from opencareyes.core.screen_dimmer import ScreenDimmer
from opencareyes.diagnostics import configure_logging
from opencareyes.platform.context_sensor import ContextSensor
from opencareyes.platform.hotkeys import HotkeyManager
from opencareyes.platform.windows_event_hub import WindowsEventHub
from opencareyes.ui.break_overlay import BreakOverlay
from opencareyes.ui.break_prompt import BreakPrompt
from opencareyes.ui.main_panel import DeferredMainPanel
from opencareyes.ui.mini_countdown import MiniCountdownWidget
from opencareyes.ui.onboarding import OnboardingDialog
from opencareyes.ui.tray_icon import TrayIcon


log = logging.getLogger(__name__)


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
    )
    dimmer.operation_failed.connect(controller.operation_failed)
    focus_mode.operation_failed.connect(controller.operation_failed)

    panel = DeferredMainPanel(controller)
    mini_countdown = MiniCountdownWidget(controller)
    session_notifications_available = event_hub.register_window(
        int(mini_countdown.winId())
    )
    # Keep every top-level reminder surface alive for the application lifetime.
    _break_overlay = BreakOverlay(controller)
    _break_prompt = BreakPrompt(controller)
    tray = TrayIcon(controller, panel, mini_countdown)

    if not session_notifications_available:
        log.warning("Windows session notifications are unavailable")
        QTimer.singleShot(
            0,
            lambda: controller.operation_failed.emit(
                "session_notifications_unavailable",
                "锁屏状态检测暂时不可用；应用仍会继续检测全屏和空闲状态。",
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
    event_hub.session_locked.connect(refresh_after_session_change)
    event_hub.system_suspended.connect(refresh_after_session_change)

    def apply_state_theme(state) -> None:
        app.apply_theme(state.general.theme)

    controller.state_changed.connect(apply_state_theme)
    app.activation_requested.connect(panel.show_and_activate)
    tray.show()
    app.apply_theme(controller.state.general.theme)
    # Prime the context sensor before restoring persisted effects. Starting
    # inside a full-screen presentation must never flash a focus/rest overlay.
    context_runtime.start()
    controller.attach_context_runtime(context_runtime)
    controller.restore()

    def present_first_run() -> None:
        if controller.state.general.onboarding_completed:
            return
        panel.show_and_activate()
        onboarding = OnboardingDialog(controller, panel.widget)
        onboarding.exec()
        if controller.state.general.onboarding_completed:
            tray.showMessage(
                "OpenCareEyes 已准备好",
                "程序会常驻系统托盘；左键打开主界面，右键快速控制。",
            )

    QTimer.singleShot(0, present_first_run)

    def on_exit() -> None:
        context_runtime.stop()
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
