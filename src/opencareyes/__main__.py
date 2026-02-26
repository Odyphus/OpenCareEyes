"""Entry point: python -m opencareyes"""

import sys
import logging

from opencareyes.app import OpenCareEyesApp
from opencareyes.config.settings import Settings
from opencareyes.core.blue_light_filter import BlueLightFilter
from opencareyes.core.screen_dimmer import ScreenDimmer
from opencareyes.core.break_reminder import BreakReminder
from opencareyes.core.focus_mode import FocusMode
from opencareyes.core.scheduler import Scheduler
from opencareyes.platform.hotkeys import HotkeyManager
from opencareyes.ui.tray_icon import TrayIcon
from opencareyes.ui.main_panel import MainPanel
from opencareyes.ui.break_overlay import BreakOverlay
from opencareyes.ui.mini_countdown import MiniCountdownWidget

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
log = logging.getLogger(__name__)


def main():
    app = OpenCareEyesApp(sys.argv)
    if not app.ensure_single_instance():
        log.info("Another instance is already running. Exiting.")
        sys.exit(0)

    settings = Settings()

    # Core modules
    blue_filter = BlueLightFilter()
    dimmer = ScreenDimmer()
    break_reminder = BreakReminder()
    focus_mode = FocusMode()
    scheduler = Scheduler(blue_filter, settings)
    hotkeys = HotkeyManager()

    # UI
    break_overlay = BreakOverlay()
    mini_countdown = MiniCountdownWidget()
    panel = MainPanel(settings, blue_filter, dimmer, break_reminder, focus_mode)
    tray = TrayIcon(settings, blue_filter, dimmer, break_reminder, focus_mode, panel, mini_countdown)
    tray.show()

    # Connect break overlay to break reminder signals
    break_reminder.break_started.connect(
        lambda: break_overlay.start_break(
            settings.break_duration, force=settings.force_break
        )
    )
    break_reminder.break_ended.connect(break_overlay.end_break)
    break_overlay.skip_requested.connect(break_reminder.skip_break)

    # Connect mini countdown widget to break reminder tick
    def on_break_tick(remaining, total):
        if break_reminder.is_on_break:
            mini_countdown.set_break_mode()
        else:
            mini_countdown.update_countdown(remaining)

    break_reminder.tick.connect(on_break_tick)

    # Show mini countdown if break reminder is enabled
    # Position it at bottom-right corner
    def update_mini_countdown_visibility():
        if settings.break_enabled and break_reminder.enabled:
            from PySide6.QtWidgets import QApplication
            screen = QApplication.primaryScreen().geometry()
            mini_countdown.move(screen.width() - 160, screen.height() - 100)
            mini_countdown.show()
        else:
            mini_countdown.hide()

    update_mini_countdown_visibility()

    # Restore state from settings
    if settings.filter_enabled:
        blue_filter.enable(settings.color_temperature)
    if settings.dimmer_enabled:
        dimmer.enable(settings.dim_level)
    if settings.break_enabled:
        break_reminder.set_mode(settings.break_mode)
        break_reminder.set_work_duration(settings.work_duration)
        break_reminder.set_break_duration(settings.break_duration)
        break_reminder.force_break = settings.force_break
        break_reminder.start()
    if settings.focus_enabled:
        focus_mode.set_dim_level(settings.focus_dim_level)
        focus_mode.enable()
    if settings.filter_schedule_enabled:
        scheduler.start()

    # Hotkeys
    hotkeys.register(settings.hotkey_filter, lambda: tray.toggle_filter())
    hotkeys.register(settings.hotkey_break, lambda: tray.toggle_break())
    hotkeys.register(settings.hotkey_dimmer, lambda: tray.toggle_dimmer())
    hotkeys.register(settings.hotkey_focus, lambda: tray.toggle_focus())

    def on_exit():
        blue_filter.disable()
        dimmer.disable()
        focus_mode.disable()
        hotkeys.unregister_all()
        scheduler.stop()
        settings.sync()
        app.cleanup()

    app.aboutToQuit.connect(on_exit)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
