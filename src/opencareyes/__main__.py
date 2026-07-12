"""OpenCareEyes application entry point."""

from __future__ import annotations

import logging
import sys

from PySide6.QtCore import QTimer

from opencareyes.app import OpenCareEyesApp
from opencareyes.config.settings import Settings
from opencareyes.controller import AppController
from opencareyes.core.blue_light_filter import BlueLightFilter
from opencareyes.core.break_reminder import BreakReminder
from opencareyes.core.focus_mode import FocusMode
from opencareyes.core.scheduler import Scheduler
from opencareyes.core.screen_dimmer import ScreenDimmer
from opencareyes.diagnostics import configure_logging
from opencareyes.platform.hotkeys import HotkeyManager
from opencareyes.ui.break_overlay import BreakOverlay
from opencareyes.ui.main_panel import MainPanel
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

    settings = Settings()
    blue_filter = BlueLightFilter()
    dimmer = ScreenDimmer()
    break_reminder = BreakReminder()
    focus_mode = FocusMode()
    scheduler = Scheduler(settings=settings)
    hotkeys = HotkeyManager()

    controller = AppController(
        settings=settings,
        blue_filter=blue_filter,
        dimmer=dimmer,
        break_reminder=break_reminder,
        focus_mode=focus_mode,
        scheduler=scheduler,
        hotkeys=hotkeys,
    )

    panel = MainPanel(controller)
    mini_countdown = MiniCountdownWidget(controller)
    # Keep the top-level overlay alive for the whole application lifetime.
    _break_overlay = BreakOverlay(controller)
    tray = TrayIcon(controller, panel, mini_countdown)

    def apply_state_theme(state) -> None:
        app.apply_theme(state.general.theme)

    controller.state_changed.connect(apply_state_theme)
    app.activation_requested.connect(panel.show_and_activate)
    tray.show()
    app.apply_theme(controller.state.general.theme)
    controller.restore()

    def present_first_run() -> None:
        if controller.state.general.onboarding_completed:
            return
        panel.show_and_activate()
        onboarding = OnboardingDialog(controller, panel)
        onboarding.exec()
        if controller.state.general.onboarding_completed:
            tray.showMessage(
                "OpenCareEyes 已准备好",
                "程序会常驻系统托盘；左键打开主界面，右键快速控制。",
            )

    QTimer.singleShot(0, present_first_run)

    def on_exit() -> None:
        # Runtime effects must be removed without overwriting the user's saved
        # preferences, so shutdown calls services directly by design.
        break_reminder.stop()
        scheduler.stop()
        hotkeys.unregister_all()
        focus_mode.disable()
        dimmer.disable()
        blue_filter.disable()
        settings.sync()
        app.cleanup()

    app.aboutToQuit.connect(on_exit)
    exit_code = app.exec()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
