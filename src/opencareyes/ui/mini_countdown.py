"""Optional always-on-top countdown companion."""

from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    QRectF,
    Qt,
    QTimer,
    QVariantAnimation,
)
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPalette, QPen
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from opencareyes.ui.widgets import first_state_value


_MOOD_COLORS = {
    "working": "#5B8DEF",
    "resting": "#58B891",
    "paused": "#7D8799",
}

_THEME_COLORS = {
    "dark": {
        "card": "#111724",
        "border": "#FFFFFF",
        "text": "#FFFFFF",
        "label": "#EBF1FC",
        "hint": "#BBC7DC",
        "feature": "#101827",
        "close_hover": "#FFFFFF",
    },
    "light": {
        "card": "#F7FAFF",
        "border": "#9AA9C0",
        "text": "#172033",
        "label": "#34435C",
        "hint": "#596981",
        "feature": "#101827",
        "close_hover": "#172033",
    },
}


def _blend_color(start: QColor, end: QColor, progress: float) -> QColor:
    progress = max(0.0, min(1.0, float(progress)))
    return QColor(
        round(start.red() + (end.red() - start.red()) * progress),
        round(start.green() + (end.green() - start.green()) * progress),
        round(start.blue() + (end.blue() - start.blue()) * progress),
        round(start.alpha() + (end.alpha() - start.alpha()) * progress),
    )


class _PetFace(QWidget):
    """Small original mascot drawn with Qt primitives."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mood = "working"
        self._accent = QColor(_MOOD_COLORS["working"])
        self._theme = "dark"
        self._blinking = False
        self.setFixedSize(82, 88)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAccessibleName("护眼倒计时小伙伴")

    @property
    def mood(self) -> str:
        return self._mood

    @property
    def blinking(self) -> bool:
        return self._blinking

    def set_mood(self, mood: str) -> None:
        selected = mood if mood in _MOOD_COLORS else "working"
        if selected != self._mood:
            self._mood = selected
            self.update()

    def set_accent(self, accent: QColor) -> None:
        if accent != self._accent:
            self._accent = QColor(accent)
            self.update()

    def set_theme(self, theme: str) -> None:
        selected = theme if theme in _THEME_COLORS else "dark"
        if selected != self._theme:
            self._theme = selected
            self.update()

    def set_blinking(self, blinking: bool) -> None:
        blinking = bool(blinking)
        if blinking != self._blinking:
            self._blinking = blinking
            self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        accent = self._accent
        palette = _THEME_COLORS[self._theme]
        feature_color = QColor(palette["feature"])
        body = QRectF(10, 20, 62, 57)

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 48 if self._theme == "dark" else 32))
        painter.drawRoundedRect(body.translated(0, 3), 18, 18)
        painter.setPen(
            QPen(
                QColor(255, 255, 255, 80)
                if self._theme == "dark"
                else QColor(255, 255, 255, 150),
                1.2,
            )
        )
        painter.setBrush(accent)
        painter.drawRoundedRect(body, 18, 18)

        # A warm sprout makes the character distinctive without relying on an
        # external mascot asset.
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#F2A65A"))
        painter.drawEllipse(QRectF(34, 8, 13, 16))
        painter.setBrush(QColor("#F7C77F"))
        painter.drawEllipse(QRectF(43, 11, 12, 10))

        eye_pen = QPen(feature_color, 3.2, Qt.SolidLine, Qt.RoundCap)
        painter.setPen(eye_pen)
        if self._mood == "resting" or self._blinking:
            painter.drawLine(26, 47, 33, 47)
            painter.drawLine(49, 47, 56, 47)
        else:
            painter.drawPoint(30, 47)
            painter.drawPoint(52, 47)

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(255, 137, 153, 155))
        painter.drawEllipse(QRectF(19, 54, 8, 5))
        painter.drawEllipse(QRectF(55, 54, 8, 5))

        mouth = QPainterPath()
        if self._mood == "paused":
            mouth.moveTo(37, 60)
            mouth.lineTo(45, 60)
        elif self._mood == "resting":
            mouth.moveTo(36, 59)
            mouth.cubicTo(39, 62, 43, 62, 46, 59)
        else:
            mouth.moveTo(36, 58)
            mouth.cubicTo(39, 64, 43, 64, 46, 58)
        painter.setPen(QPen(feature_color, 2, Qt.SolidLine, Qt.RoundCap))
        painter.drawPath(mouth)

        painter.setPen(QPen(accent.lighter(135), 3, Qt.SolidLine, Qt.RoundCap))
        painter.drawLine(24, 79, 32, 79)
        painter.drawLine(50, 79, 58, 79)


class MiniCountdownWidget(QWidget):
    """Draggable countdown pet backed by the authoritative break state."""

    def __init__(self, controller=None, parent=None):
        super().__init__(parent)
        self._controller = controller
        self._mood = "working"
        self._accent = QColor(_MOOD_COLORS["working"])
        self._target_accent = QColor(self._accent)
        self._transition_start = QColor(self._accent)
        self._theme = "dark"
        self._motion_mode = "system"
        self._system_motion_enabled = True
        self._motion_enabled = True
        self._dragging = False
        self._drag_pos = None
        self._positioned = False
        self._has_faded_in = False

        self.setObjectName("miniCountdown")
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedSize(260, 112)
        self.setAccessibleName("休息倒计时桌宠")
        self.setToolTip("拖动桌宠可调整位置；点击右上角可隐藏")

        self._build_ui()
        self._build_animations()
        self._connect_app_preferences()

        if controller is not None:
            controller.state_changed.connect(self.render)
            self.render(controller.state)

    @property
    def mood(self) -> str:
        return self._mood

    @property
    def theme(self) -> str:
        return self._theme

    @property
    def motion_enabled(self) -> bool:
        return self._motion_enabled

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 10, 10)
        layout.setSpacing(8)

        self._pet = _PetFace(self)
        layout.addWidget(self._pet)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 15, 0, 13)
        text_layout.setSpacing(1)

        self._label = QLabel("距离下次休息")
        self._label.setFont(QFont("Microsoft YaHei UI", 9))
        self._label.setAttribute(Qt.WA_TransparentForMouseEvents)
        text_layout.addWidget(self._label)

        self._countdown_label = QLabel("--:--")
        self._countdown_label.setFont(
            QFont("Microsoft YaHei UI", 23, QFont.DemiBold)
        )
        self._countdown_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        text_layout.addWidget(self._countdown_label)

        self._hint_label = QLabel("护眼小伙伴正在陪你")
        self._hint_label.setFont(QFont("Microsoft YaHei UI", 9))
        self._hint_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        text_layout.addWidget(self._hint_label)
        layout.addLayout(text_layout, 1)

        close_layout = QVBoxLayout()
        close_layout.setContentsMargins(0, 1, 0, 0)
        self._close_button = QToolButton(self)
        self._close_button.setText("×")
        self._close_button.setFixedSize(24, 24)
        self._close_button.setCursor(Qt.PointingHandCursor)
        self._close_button.setAccessibleName("隐藏倒计时桌宠")
        self._close_button.setToolTip("隐藏桌宠，可在休息节奏中重新开启")
        self._close_button.clicked.connect(self.hide_pet)
        close_layout.addWidget(self._close_button)
        close_layout.addStretch()
        layout.addLayout(close_layout)

    def _build_animations(self) -> None:
        self._fade_animation = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade_animation.setDuration(160)
        self._fade_animation.setEasingCurve(QEasingCurve.OutCubic)
        self._fade_animation.setStartValue(0.0)
        self._fade_animation.setEndValue(1.0)

        self._mood_animation = QVariantAnimation(self)
        self._mood_animation.setDuration(180)
        self._mood_animation.setEasingCurve(QEasingCurve.InOutCubic)
        self._mood_animation.setStartValue(0.0)
        self._mood_animation.setEndValue(1.0)
        self._mood_animation.valueChanged.connect(self._advance_mood_transition)

        self._blink_timer = QTimer(self)
        self._blink_timer.setInterval(15_000)
        self._blink_timer.timeout.connect(self._start_blink)
        self._blink_close_timer = QTimer(self)
        self._blink_close_timer.setSingleShot(True)
        self._blink_close_timer.setInterval(160)
        self._blink_close_timer.timeout.connect(self._finish_blink)

    def _connect_app_preferences(self) -> None:
        app = QApplication.instance()
        if app is None:
            self._apply_theme("dark")
            return

        resolved_theme = getattr(app, "resolved_theme", None)
        if resolved_theme not in _THEME_COLORS:
            resolved_theme = app.property("resolvedTheme")
        if resolved_theme not in _THEME_COLORS:
            window_color = app.palette().color(QPalette.Window)
            resolved_theme = "dark" if window_color.lightness() < 128 else "light"
        self._apply_theme(str(resolved_theme))

        self._system_motion_enabled = bool(getattr(app, "motion_enabled", True))
        theme_signal = getattr(app, "theme_changed", None)
        if theme_signal is not None:
            theme_signal.connect(self._apply_theme)
        motion_signal = getattr(app, "motion_changed", None)
        if motion_signal is not None:
            motion_signal.connect(self._on_system_motion_changed)
        self._refresh_motion_preference()

    def _apply_theme(self, theme: str) -> None:
        selected = theme if theme in _THEME_COLORS else "dark"
        self._theme = selected
        palette = _THEME_COLORS[selected]
        self._label.setStyleSheet(
            f"color: {palette['label']}; background: transparent;"
        )
        self._countdown_label.setStyleSheet(
            f"color: {palette['text']}; background: transparent;"
        )
        self._hint_label.setStyleSheet(
            f"color: {palette['hint']}; background: transparent;"
        )
        self._close_button.setStyleSheet(
            f"QToolButton {{ color: {palette['label']}; "
            "background: rgba(127,127,127,20); border: none; "
            "border-radius: 12px; font-size: 17px; }"
            f"QToolButton:hover, QToolButton:focus {{ color: {palette['close_hover']}; "
            "background: rgba(127,127,127,44); }"
        )
        self._pet.set_theme(selected)
        self.update()

    def _on_system_motion_changed(self, enabled: bool) -> None:
        self._system_motion_enabled = bool(enabled)
        if self._motion_mode == "system":
            self._refresh_motion_preference()

    def set_motion_mode(self, mode: str) -> None:
        """Apply system, standard or reduced motion without requiring state v3."""
        selected = mode if mode in {"system", "standard", "reduced"} else "system"
        if selected != self._motion_mode:
            self._motion_mode = selected
            self._refresh_motion_preference()

    def _refresh_motion_preference(self) -> None:
        enabled = (
            self._system_motion_enabled
            if self._motion_mode == "system"
            else self._motion_mode == "standard"
        )
        changed = enabled != self._motion_enabled
        self._motion_enabled = enabled
        if not enabled:
            self._stop_animations(snap_to_final=True)
        elif changed:
            self._sync_blink_timer()

    def _stop_animations(self, *, snap_to_final: bool) -> None:
        self._fade_animation.stop()
        self._mood_animation.stop()
        self._blink_timer.stop()
        self._blink_close_timer.stop()
        self._pet.set_blinking(False)
        if snap_to_final:
            self.setWindowOpacity(1.0)
            self._accent = QColor(self._target_accent)
            self._pet.set_accent(self._accent)
            self.update()

    def _sync_blink_timer(self) -> None:
        should_run = self.isVisible() and self._motion_enabled and self._mood == "working"
        if should_run:
            if not self._blink_timer.isActive():
                self._blink_timer.start()
        else:
            self._blink_timer.stop()
            self._blink_close_timer.stop()
            self._pet.set_blinking(False)

    def _start_blink(self) -> None:
        if not (self.isVisible() and self._motion_enabled and self._mood == "working"):
            self._sync_blink_timer()
            return
        self._pet.set_blinking(True)
        self._blink_close_timer.start()

    def _finish_blink(self) -> None:
        self._pet.set_blinking(False)

    def move_to_default(self) -> None:
        app = QApplication.instance()
        screen = app.primaryScreen() if app is not None else None
        if screen is None:
            return
        area = screen.availableGeometry()
        self.move(area.right() - self.width() - 18, area.bottom() - self.height() - 18)
        self._positioned = True

    def update_countdown(self, remaining_seconds: int) -> None:
        minutes, seconds = divmod(max(0, int(remaining_seconds)), 60)
        self._countdown_label.setText(f"{minutes}:{seconds:02d}")
        self.setAccessibleDescription(
            f"{self._label.text()}，剩余 {minutes} 分 {seconds} 秒"
        )

    def set_break_mode(self) -> None:
        self._set_mood("resting")
        self._label.setText("休息时间")
        self._hint_label.setText("看看远处，慢慢放松")
        self._countdown_label.setText("放松一下")
        self.setAccessibleDescription("当前正在休息")

    def hide_pet(self) -> None:
        self.hide()
        if self._controller is not None:
            self._controller.set_break_countdown_display("tray")

    def render(self, state) -> None:
        self.set_motion_mode(
            str(first_state_value(state, "general.motion_mode", default="system"))
        )
        enabled = bool(first_state_value(state, "breaks.enabled", default=False))
        policy_desired = bool(
            first_state_value(
                state,
                "effective_policy.breaks.desired_enabled",
                default=enabled,
            )
        )
        effective_enabled = bool(
            first_state_value(
                state,
                "effective_policy.breaks.effective_enabled",
                default=enabled,
            )
        )
        suppressed_by = tuple(
            first_state_value(
                state,
                "effective_policy.breaks.suppressed_by",
                default=(),
            )
            or ()
        )
        # A v0.2 controller (or a partially constructed test state) has no
        # projected runtime policy. In that case the authoritative legacy
        # preference remains ``breaks.enabled``.
        if policy_desired != enabled:
            effective_enabled = enabled
            suppressed_by = ()
        phase = str(first_state_value(state, "breaks.phase", default="stopped"))
        paused = bool(first_state_value(state, "breaks.paused", default=False))
        remaining = int(first_state_value(state, "breaks.remaining", default=0))
        display_mode = str(
            first_state_value(state, "breaks.countdown_display", default="tray")
        )

        if (
            not enabled
            or not effective_enabled
            or suppressed_by
            or display_mode != "floating"
        ):
            self.hide()
            return

        if paused:
            self._set_mood("paused")
            self._label.setText("休息已暂停" if phase == "resting" else "计时已暂停")
            self._hint_label.setText(
                "继续后完成剩余休息" if phase == "resting" else "准备好后再继续"
            )
        elif phase == "resting":
            self._set_mood("resting")
            self._label.setText("休息时间")
            self._hint_label.setText("看看远处，慢慢放松")
        else:
            self._set_mood("working")
            self._label.setText("距离下次休息")
            self._hint_label.setText("护眼小伙伴正在陪你")

        self.update_countdown(remaining)
        if not self.isVisible():
            if not self._positioned:
                self.move_to_default()
            self.show()

    def _set_mood(self, mood: str) -> None:
        selected = mood if mood in _MOOD_COLORS else "working"
        if selected == self._mood:
            self._sync_blink_timer()
            return

        self._mood = selected
        self._pet.set_mood(selected)
        self._target_accent = QColor(_MOOD_COLORS[selected])
        if self.isVisible() and self._motion_enabled:
            self._mood_animation.stop()
            self._transition_start = QColor(self._accent)
            self._mood_animation.start()
        else:
            self._accent = QColor(self._target_accent)
            self._pet.set_accent(self._accent)
            self.update()
        self._sync_blink_timer()

    def _advance_mood_transition(self, progress) -> None:
        self._accent = _blend_color(
            self._transition_start,
            self._target_accent,
            float(progress),
        )
        self._pet.set_accent(self._accent)
        self.update()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._has_faded_in:
            self._has_faded_in = True
            if self._motion_enabled:
                self.setWindowOpacity(0.0)
                self._fade_animation.start()
            else:
                self.setWindowOpacity(1.0)
        else:
            self.setWindowOpacity(1.0)
        self._sync_blink_timer()

    def hideEvent(self, event) -> None:
        self._stop_animations(snap_to_final=True)
        super().hideEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        card = QRectF(4, 3, self.width() - 8, self.height() - 10)
        palette = _THEME_COLORS[self._theme]

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 72 if self._theme == "dark" else 42))
        painter.drawRoundedRect(card.translated(0, 4), 18, 18)
        border = QColor(palette["border"])
        border.setAlpha(30 if self._theme == "dark" else 90)
        painter.setPen(QPen(border, 1))
        card_color = QColor(palette["card"])
        card_color.setAlpha(242 if self._theme == "dark" else 248)
        painter.setBrush(card_color)
        painter.drawRoundedRect(card, 18, 18)

        painter.setPen(Qt.NoPen)
        painter.setBrush(self._accent)
        painter.drawRoundedRect(
            QRectF(18, self.height() - 10, self.width() - 36, 3),
            1.5,
            1.5,
        )

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._dragging = True
            self._drag_pos = event.globalPosition().toPoint() - self.pos()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._dragging and self._drag_pos is not None:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            self._positioned = True
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._dragging = False
            self._drag_pos = None
            event.accept()
        else:
            super().mouseReleaseEvent(event)
