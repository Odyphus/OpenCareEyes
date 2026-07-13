"""Capture deterministic README screenshots from the real Qt widgets."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from opencareyes.constants import STYLES_DIR
from opencareyes.state import (
    AppState,
    AutomationState,
    BreakCadenceState,
    BreakState,
    CapabilitiesState,
    ContextState,
    DisplayState,
    DisplayHealthState,
    EffectivePolicyState,
    FeatureRuntimeState,
    FocusState,
    GeneralState,
    GlobalPauseState,
)
from opencareyes.ui.main_panel import MainPanel


class DemoController(QObject):
    state_changed = Signal(object)
    break_tick = Signal(int, int)
    operation_failed = Signal(str, str)
    notification_requested = Signal(str, str)

    def __init__(self, theme: str):
        super().__init__()
        next_event = datetime.now().astimezone() + timedelta(hours=2, minutes=18)
        self.state = AppState(
            display=DisplayState(
                filter_enabled=True,
                color_temperature=4500,
                dimmer_enabled=True,
                dim_level=36,
                preset="reading",
            ),
            breaks=BreakState(
                enabled=True,
                phase="working",
                mode="20-20-20",
                work_duration=20 * 60,
                break_duration=20,
                remaining=18 * 60 + 24,
                total=20 * 60,
                force_break=False,
                countdown_display="floating",
            ),
            focus=FocusState(enabled=False, dim_level=150),
            automation=AutomationState(
                enabled=True,
                mode="sun",
                next_event="sunset",
                next_event_at=next_event,
            ),
            global_pause=GlobalPauseState(),
            capabilities=CapabilitiesState(
                filter_available=True,
                dimmer_available=True,
                breaks_available=True,
                focus_available=True,
                automation_available=True,
                hotkeys_available=True,
            ),
            general=GeneralState(
                theme=theme,
                autostart=True,
                onboarding_completed=True,
                location_configured=True,
                city="上海",
                latitude=31.2304,
                longitude=121.4737,
            ),
            context=ContextState(
                foreground_app_id="code.exe",
                recent_app_id="code.exe",
            ),
            effective_policy=EffectivePolicyState(
                filter=FeatureRuntimeState(True, True),
                dimmer=FeatureRuntimeState(True, True),
                breaks=FeatureRuntimeState(True, True),
                focus=FeatureRuntimeState(False, False),
            ),
            display_health=DisplayHealthState(
                backend="Windows GDI Gamma + 覆盖层",
                status="ok",
                message="显示效果已验证",
            ),
            break_cadence=BreakCadenceState(
                mode="20-20-20",
                short_remaining=18 * 60 + 24,
            ),
        )

    def __getattr__(self, _name):
        return lambda *args, **kwargs: True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--theme", choices=("light", "dark"), required=True)
    parser.add_argument(
        "--page",
        choices=("总览", "屏幕舒适度", "休息节奏", "专注模式", "自动化", "设置"),
        default="总览",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    app = QApplication.instance() or QApplication(sys.argv)
    fonts_dir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    for filename in ("segoeui.ttf", "msyh.ttc"):
        path = fonts_dir / filename
        if path.is_file():
            QFontDatabase.addApplicationFont(str(path))
    app.setFont(QFont("Microsoft YaHei UI", 10))
    stylesheet = Path(STYLES_DIR) / f"{args.theme}.qss"
    app.setStyleSheet(stylesheet.read_text(encoding="utf-8"))
    panel = MainPanel(DemoController(args.theme))
    # The offscreen plugin exposes an 800 px virtual desktop. Keep the real
    # 920x640 product layout for documentation captures instead of triggering
    # the compact responsive fallback used on genuinely small screens.
    panel._fit_available_geometry = lambda: None
    panel.show()
    app.processEvents()
    QTest.qWait(100)
    panel.show_page(args.page)
    app.processEvents()
    if args.page == "自动化":
        page = panel._stack.currentWidget()
        page.verticalScrollBar().setValue(420)
        app.processEvents()
    # Native Windows widgets can finish their first paint asynchronously.
    # Waiting for one short paint cycle avoids partially rendered README art.
    QTest.qWait(200)
    app.processEvents()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.page == "设置":
        # QLineEdit-heavy pages render more reliably through the native
        # backing store on Windows at 200% scaling.
        saved = panel.grab().save(str(args.output), "PNG")
    else:
        scale = panel.devicePixelRatioF()
        frame = QPixmap(round(panel.width() * scale), round(panel.height() * scale))
        frame.setDevicePixelRatio(scale)
        frame.fill(QColor("#f4f7fb" if args.theme == "light" else "#0c1118"))
        panel.render(frame)
        saved = frame.save(str(args.output), "PNG")
    panel.close()
    return 0 if saved else 1


if __name__ == "__main__":
    raise SystemExit(main())
