"""Calm, escapable full-screen break reminder."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QKeyEvent, QPainter
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from opencareyes.ui.widgets import first_state_value


_TIPS = (
    "看向约 6 米外的物体，让眼睛慢慢放松。",
    "轻轻闭眼，放松眼周与肩颈。",
    "缓慢眨眼十次，让眼睛保持湿润。",
    "站起来伸展身体，再做几次深呼吸。",
)


class BreakOverlay(QWidget):
    skip_requested = Signal()
    snooze_requested = Signal(int)
    resume_requested = Signal()

    def __init__(self, controller=None, parent=None):
        super().__init__(parent)
        self._controller = controller
        self.setObjectName("breakOverlay")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAccessibleName("全屏休息提醒")
        self._remaining = 0
        self._force = False
        self._kind = "short"
        self._tip_index = 0
        self._fallback_timer = QTimer(self)
        self._fallback_timer.setInterval(1000)
        self._fallback_timer.timeout.connect(self._fallback_tick)
        self._build_ui()

        if controller is not None:
            controller.state_changed.connect(self.render)
            break_tick = getattr(controller, "break_tick", None)
            if break_tick is not None:
                break_tick.connect(self._on_break_tick)
            self.skip_requested.connect(controller.skip_break)
            self.snooze_requested.connect(controller.snooze_break)
            resume_break = getattr(controller, "resume_break", None)
            if resume_break is not None:
                self.resume_requested.connect(resume_break)
            self.render(controller.state)
        else:
            self.skip_requested.connect(self.end_break)
            self.snooze_requested.connect(lambda _minutes: self.end_break())

    def _build_ui(self) -> None:
        self._title_label = QLabel("该休息一下眼睛了")
        self._title_label.setAlignment(Qt.AlignCenter)
        self._title_label.setFont(QFont("Segoe UI", 28, QFont.DemiBold))
        self._title_label.setStyleSheet("color: white; background: transparent;")
        self._countdown_label = QLabel("0:00")
        self._countdown_label.setAlignment(Qt.AlignCenter)
        self._countdown_label.setFont(QFont("Segoe UI", 64, QFont.DemiBold))
        self._countdown_label.setStyleSheet("color: white; background: transparent;")
        self._tip_label = QLabel("")
        self._tip_label.setAlignment(Qt.AlignCenter)
        self._tip_label.setFont(QFont("Segoe UI", 15))
        self._tip_label.setStyleSheet("color: rgba(255,255,255,190); background: transparent;")
        self._tip_label.setWordWrap(True)

        self._snooze_button = QPushButton("5 分钟后提醒")
        self._resume_button = QPushButton("继续休息计时")
        self._skip_button = QPushButton("结束本次休息")
        for button in (self._snooze_button, self._resume_button, self._skip_button):
            button.setMinimumSize(136, 42)
            button.setStyleSheet(
                "QPushButton { color: white; background: rgba(255,255,255,28); "
                "border: 1px solid rgba(255,255,255,70); border-radius: 10px; padding: 8px 16px; }"
                "QPushButton:hover, QPushButton:focus { background: rgba(255,255,255,48); "
                "border-color: rgba(255,255,255,150); }"
            )
        self._snooze_button.setAccessibleName("5 分钟后再次提醒")
        self._resume_button.setAccessibleName("继续休息倒计时")
        self._skip_button.setAccessibleName("安全结束本次休息")
        self._snooze_button.clicked.connect(lambda: self.snooze_requested.emit(5))
        self._resume_button.clicked.connect(self.resume_requested.emit)
        self._skip_button.clicked.connect(self.skip_requested.emit)

        actions = QHBoxLayout()
        actions.addStretch()
        actions.addWidget(self._snooze_button)
        actions.addWidget(self._resume_button)
        actions.addWidget(self._skip_button)
        actions.addStretch()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(48, 48, 48, 48)
        layout.addStretch()
        layout.addWidget(self._title_label)
        layout.addSpacing(18)
        layout.addWidget(self._countdown_label)
        layout.addSpacing(14)
        layout.addWidget(self._tip_label)
        layout.addSpacing(30)
        layout.addLayout(actions)
        layout.addStretch()

    def start_break(self, duration_seconds: int, force: bool = False) -> None:
        """Compatibility entry point for integrations without a controller."""

        self._remaining = max(0, int(duration_seconds))
        self._show_break(force, paused=False)
        if self._controller is None:
            self._fallback_timer.start()

    def end_break(self) -> None:
        self._fallback_timer.stop()
        self._force = False
        self.hide()

    def _show_break(self, force: bool, paused: bool, kind: str = "short") -> None:
        self._force = bool(force)
        self._kind = "long" if kind == "long" else "short"
        if paused:
            title = "休息计时已暂停"
        elif self._force:
            title = "现在是严格休息时间"
        elif self._kind == "long":
            title = "现在进行一次长休息"
        else:
            title = "该休息一下眼睛了"
        self._title_label.setText(title)
        self._snooze_button.setVisible(not self._force)
        self._resume_button.setVisible(paused)
        self._skip_button.setText(
            "安全结束本次休息" if self._force else "结束本次休息"
        )
        self._update_display()
        self._cover_all_screens()
        if not self.isVisible():
            self._tip_label.setText(_TIPS[self._tip_index % len(_TIPS)])
            self._tip_index += 1
            self.show()
            self.raise_()
            self.activateWindow()
        # Safety exit remains available even for strict rest mode.
        self._skip_button.setVisible(True)

    def render(self, state) -> None:
        enabled = bool(first_state_value(state, "breaks.enabled", default=False))
        phase = str(first_state_value(state, "breaks.phase", default="stopped"))
        paused = bool(first_state_value(state, "breaks.paused", default=False))
        self._remaining = int(first_state_value(state, "breaks.remaining", default=0))
        force = bool(first_state_value(state, "breaks.force_break", default=False))
        kind = str(first_state_value(
            state,
            "break_prompt.kind",
            "breaks.current_break_kind",
            "breaks.cadence.current_break_kind",
            default="short",
        ))
        suppressed = tuple(first_state_value(
            state, "effective_policy.breaks.suppressed_by", default=()
        ))
        # Every active rest phase gets a visible full-screen surface.  Strict
        # mode controls postponement, not whether the reminder can be seen.
        if enabled and phase == "resting" and not suppressed:
            self._show_break(force, paused, kind)
        else:
            self.end_break()

    def _on_break_tick(self, *values) -> None:
        """Consume either ``(remaining, total)`` or a tick-state object."""

        if not values:
            return
        if len(values) >= 2:
            remaining = values[0]
        else:
            tick = values[0]
            if isinstance(tick, dict):
                remaining = tick.get("remaining", self._remaining)
            else:
                remaining = getattr(tick, "remaining", self._remaining)
        self._remaining = max(0, int(remaining))
        if self.isVisible():
            self._update_display()

    def _fallback_tick(self) -> None:
        self._remaining -= 1
        self._update_display()
        if self._remaining <= 0:
            self.end_break()

    def _update_display(self) -> None:
        minutes, seconds = divmod(max(0, self._remaining), 60)
        text = f"{minutes}:{seconds:02d}"
        self._countdown_label.setText(text)
        self.setAccessibleDescription(f"休息剩余 {minutes} 分 {seconds} 秒")

    def _cover_all_screens(self) -> None:
        app = QApplication.instance()
        screens = app.screens() if app is not None else []
        if not screens:
            return
        combined = screens[0].geometry()
        for screen in screens[1:]:
            combined = combined.united(screen.geometry())
        self.setGeometry(combined)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(10, 14, 24, 222))
        painter.end()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key_Escape:
            self.skip_requested.emit()
            event.accept()
        else:
            super().keyPressEvent(event)
