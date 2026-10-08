"""Calm, escapable full-screen break reminder."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QKeyEvent, QPainter
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QLayout, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from opencareyes.ui.widgets import first_state_value
from opencareyes.ui.rest_scene import GentleEntrance, RestScene
from opencareyes.ui.theme import rest_palette


_TIPS = (
    "看向约 6 米外的物体，让眼睛慢慢放松。",
    "轻轻闭眼，放松眼周与肩颈。",
    "缓慢眨眼十次，让眼睛保持湿润。",
    "站起来伸展身体，再做几次深呼吸。",
)

_REST_SCENES = {
    'gaze': (
        '把目光交给远处',
        '看向约 6 米外的物体，让眼睛慢慢放松。',
        QColor(10, 20, 39, 226),
    ),
    'snow_breathing': (
        '缓缓呼吸，放松肩颈',
        '吸气四拍，停一拍，再用六拍缓缓呼气。',
        QColor(15, 36, 58, 226),
    ),
    'stretch': (
        '和伙伴一起伸展',
        '放松肩膀，轻轻抬头，再向左右缓慢转动。',
        QColor(10, 43, 45, 226),
    ),
    'sleep': (
        '安静地休息一会儿',
        '轻轻闭眼，放松眼周、下颌与肩颈。',
        QColor(24, 22, 38, 230),
    ),
}


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
        self._scene = 'gaze'
        self._tip_index = 0
        self._theme_signature = None
        self._theme_colors: dict[str, str] = {}
        self._theme_snapshot = None
        self._entrance = GentleEntrance(self)
        self._backdrops: list[_RestBackdrop] = []
        self._active_screen = None
        self._fallback_timer = QTimer(self)
        self._fallback_timer.setInterval(1000)
        self._fallback_timer.timeout.connect(self._fallback_tick)
        self._build_ui()
        app = QApplication.instance()
        self.apply_theme(getattr(app, "theme_snapshot", None))
        if app is not None:
            app.screenAdded.connect(self._screens_changed)
            app.screenRemoved.connect(self._screens_changed)

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
        self._title_label.setAccessibleName("休息标题")
        self._title_label.setFont(QFont("Segoe UI", 25, QFont.DemiBold))
        self._title_label.setWordWrap(True)
        self._title_label.setStyleSheet("color: white; background: transparent;")
        self._countdown_label = QLabel("0:00")
        self._countdown_label.setAlignment(Qt.AlignCenter)
        self._countdown_label.setAccessibleName("休息剩余时间")
        self._countdown_label.setFont(QFont("Segoe UI", 32, QFont.Normal))
        self._countdown_label.setStyleSheet("color: white; background: transparent;")
        self._tip_label = QLabel("")
        self._tip_label.setAlignment(Qt.AlignCenter)
        self._tip_label.setAccessibleName("休息建议")
        self._tip_label.setFont(QFont("Segoe UI", 15))
        self._tip_label.setStyleSheet("color: rgba(255,255,255,190); background: transparent;")
        self._tip_label.setWordWrap(True)

        self._snooze_button = QPushButton("5 分钟后提醒")
        self._resume_button = QPushButton("继续休息计时")
        self._skip_button = QPushButton("结束本次休息")
        for button in (self._snooze_button, self._resume_button, self._skip_button):
            button.setMinimumSize(136, 42)
            button.setFocusPolicy(Qt.StrongFocus)
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
        layout.setSizeConstraint(QLayout.SetNoConstraint)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.addStretch()
        self._scene_widget = RestScene(self)
        layout.addWidget(self._scene_widget)
        layout.addSpacing(20)
        layout.addWidget(self._title_label)
        layout.addSpacing(14)
        layout.addWidget(self._tip_label)
        layout.addSpacing(24)
        layout.addWidget(self._countdown_label)
        layout.addSpacing(30)
        layout.addLayout(actions)
        self._exit_hint = QLabel("随时按 Esc 结束休息")
        self._exit_hint.setAlignment(Qt.AlignCenter)
        layout.addSpacing(12)
        layout.addWidget(self._exit_hint)
        layout.addStretch()
        self._layout = layout
        self._rest_spacers = [
            (layout.itemAt(index).spacerItem(), layout.itemAt(index).spacerItem().sizeHint().height())
            for index in range(layout.count())
            if layout.itemAt(index).spacerItem() is not None
            and layout.itemAt(index).spacerItem().sizePolicy().verticalPolicy() != QSizePolicy.Expanding
        ]

    def apply_theme(self, snapshot) -> None:
        """Apply presentation colors without changing the rest state."""

        resolved = str(getattr(snapshot, "resolved", "dark"))
        resolved = resolved if resolved in {"light", "dark"} else "dark"
        high_contrast = bool(getattr(snapshot, "high_contrast", False))
        signature = (resolved, high_contrast)
        self._theme_snapshot = snapshot
        self._entrance.configure(snapshot)
        self._theme_signature = signature
        self.setProperty("highContrast", high_contrast)

        colors = rest_palette(snapshot, self._scene)
        self._theme_colors = colors
        self._scene_widget.configure(self._scene, high_contrast)
        self._exit_hint.setStyleSheet(
            f"color: {colors['muted']}; background: transparent; font-size: 12px;"
        )
        self._title_label.setStyleSheet(f"color: {colors['title']}; background: transparent; font-size: 30px; font-weight: 600;")
        self._countdown_label.setStyleSheet(f"color: {colors['title']}; background: transparent; font-size: 36px;")
        self._tip_label.setStyleSheet(f"color: {colors['text']}; background: transparent; font-size: 16px;")
        button_style = (
            "QPushButton { border-radius: 10px; padding: 8px 16px; "
            f"color: {colors['button_text']}; background: {colors['button']}; "
            f"border: 1px solid {colors['border']}; }} "
            f"QPushButton:hover {{ border-color: {colors['focus']}; }} "
            f"QPushButton:focus {{ border: 2px solid {colors['focus']}; }}"
        )
        for button in (self._snooze_button, self._resume_button, self._skip_button):
            button.setStyleSheet(button_style)
        for backdrop in self._backdrops:
            backdrop.apply_theme(snapshot, colors["background"])
        self._adapt_layout()
        self.update()

    def _adapt_layout(self) -> None:
        compact = self.height() < 560
        self._scene_widget.setVisible(not compact and not bool(self.property('highContrast')))
        self._layout.setContentsMargins(20 if compact else 32, 12 if compact else 24,
                                       20 if compact else 32, 12 if compact else 24)
        for spacer, normal_height in self._rest_spacers:
            spacer.changeSize(0, 6 if compact else normal_height)
        self._layout.invalidate()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._adapt_layout()

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

    def hideEvent(self, event) -> None:
        self._entrance.cancel()
        for backdrop in self._backdrops:
            backdrop.hide()
        self._active_screen = None
        super().hideEvent(event)

    def closeEvent(self, event) -> None:
        self.skip_requested.emit()
        self.end_break()
        event.accept()

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
            title = _REST_SCENES[self._scene][0]
        self._title_label.setText(title)
        self._snooze_button.setVisible(not self._force)
        self._resume_button.setVisible(paused)
        self._skip_button.setText(
            "安全结束本次休息" if self._force else "结束本次休息"
        )
        self._update_display()
        self._cover_all_screens()
        if not self.isVisible():
            scene_tip = _REST_SCENES[self._scene][1]
            fallback_tip = _TIPS[self._tip_index % len(_TIPS)]
            self._tip_label.setText(scene_tip or fallback_tip)
            self._tip_index += 1
            self._entrance.show()
            self.raise_()
            self.activateWindow()
            self._skip_button.setFocus(Qt.OtherFocusReason)
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
        scene = str(first_state_value(state, 'breaks.rest_scene', default='gaze'))
        scene = scene if scene in _REST_SCENES else 'gaze'
        if scene != self._scene:
            self._scene = scene
            self.apply_theme(self._theme_snapshot)
            self._tip_label.setText(_REST_SCENES[scene][1])
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
        if self._active_screen not in screens:
            self._active_screen = app.screenAt(QCursor.pos()) or screens[0]
        area = self._active_screen.geometry()
        if self.geometry() != area:
            self.setGeometry(area)
        other_screens = [screen for screen in screens if screen != self._active_screen]
        while len(self._backdrops) < len(other_screens):
            backdrop = _RestBackdrop(self)
            backdrop.skip_requested.connect(self.skip_requested)
            self._backdrops.append(backdrop)
        for index, backdrop in enumerate(self._backdrops):
            if index >= len(other_screens):
                backdrop.hide()
                continue
            backdrop.setGeometry(other_screens[index].geometry())
            backdrop.apply_theme(self._theme_snapshot, self._theme_colors["background"])
            backdrop.entrance.show()

    def _screens_changed(self, *_args) -> None:
        if self.isVisible():
            self._cover_all_screens()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        background = self._theme_colors.get("background")
        painter.fillRect(
            self.rect(),
            QColor(background) if background else _REST_SCENES[self._scene][2],
        )
        painter.end()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key_Escape:
            self.skip_requested.emit()
            event.accept()
        else:
            super().keyPressEvent(event)


class _RestBackdrop(QWidget):
    """One quiet cover per secondary screen, never a virtual-desktop-sized HWND."""

    skip_requested = Signal()

    def __init__(self, parent):
        super().__init__(parent, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAccessibleName("休息背景，按 Esc 结束")
        self.color = "#17242C"
        self.entrance = GentleEntrance(self)

    def apply_theme(self, snapshot, color):
        self.entrance.configure(snapshot)
        self.color = color
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(self.color))

    def hideEvent(self, event):
        self.entrance.cancel()
        super().hideEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.skip_requested.emit()
            event.accept()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        self.skip_requested.emit()
        event.accept()
