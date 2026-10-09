"""Focus mode page."""

from __future__ import annotations

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtWidgets import QBoxLayout, QComboBox, QHBoxLayout, QLabel, QPushButton, QSlider

from opencareyes.ui.widgets import Card, PageHeader, ScrollPage, first_state_value, set_accessible
from opencareyes.application.status_presenter import StatusPresenter


_FOCUS_DIM_MAX = 255


class FocusPage(ScrollPage):
    """Configure background dimming and start a focus session."""

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self._controller = controller
        self._build_ui()
        self._connect_signals()
        self.render(controller.state)

    def _build_ui(self) -> None:
        self.layout.addWidget(PageHeader(
            "专注模式",
            "柔和暗化非活动区域，降低视觉干扰。可随时退出，不会锁定正在使用的窗口。",
        ))

        start_card = Card("快速开始", "选择一个专注时长，或保持开启直到手动结束。")
        row = self._session_row = QBoxLayout(QBoxLayout.LeftToRight)
        self._duration_combo = QComboBox()
        for text, minutes in (
            ("25 分钟", 25),
            ("45 分钟", 45),
            ("60 分钟", 60),
            ("持续开启", 0),
        ):
            self._duration_combo.addItem(text, minutes)
        set_accessible(self._duration_combo, "专注时长")
        self._start_button = QPushButton("开始专注")
        self._start_button.setObjectName("primaryButton")
        set_accessible(self._start_button, "开始专注")
        row.addWidget(self._duration_combo)
        row.addWidget(self._start_button)
        row.addStretch()
        start_card.body.addLayout(row)
        self._session_status = QLabel()
        self._session_status.setWordWrap(True)
        self._session_status.setObjectName('statusDetail')
        self._session_status.setAccessibleName('专注实际状态')
        start_card.body.addWidget(self._session_status)
        self.layout.addWidget(start_card)

        dim_card = Card("背景暗化", "仅调节周边区域的暗化强度。")
        value_row = QHBoxLayout()
        value_row.addWidget(QLabel("暗化程度"))
        value_row.addStretch()
        self._dim_value = QLabel("0%")
        self._dim_value.setObjectName("accentValue")
        value_row.addWidget(self._dim_value)
        dim_card.body.addLayout(value_row)
        self._dim_slider = QSlider(Qt.Horizontal)
        self._dim_slider.setRange(0, 100)
        self._dim_slider.setPageStep(10)
        set_accessible(self._dim_slider, "专注背景暗化百分比")
        dim_card.body.addWidget(self._dim_slider)
        range_row = QHBoxLayout()
        range_row.addWidget(QLabel("0%  不暗化"))
        range_row.addStretch()
        range_row.addWidget(QLabel("100%  最暗"))
        dim_card.body.addLayout(range_row)
        self.layout.addWidget(dim_card)

        note_card = Card("使用提示")
        note = QLabel("切换窗口或任务视图时，专注遮罩会自动让出；遇到全屏应用也可从托盘快速关闭。")
        note.setObjectName("cardDescription")
        note.setWordWrap(True)
        note_card.body.addWidget(note)
        self.layout.addWidget(note_card)
        self.layout.addStretch()

    def _connect_signals(self) -> None:
        self._start_button.clicked.connect(self._start_focus)
        self._dim_slider.valueChanged.connect(self._on_dim_changed)
        self._dim_slider.sliderReleased.connect(self._commit_dim)
        self._controller.state_changed.connect(self.render)

    def _start_focus(self) -> None:
        if bool(first_state_value(self._controller.state, 'focus.enabled', default=False)):
            self._controller.set_feature_enabled('focus', False)
            return
        minutes = int(self._duration_combo.currentData())
        start_session = getattr(self._controller, "start_focus_session", None)
        if minutes and callable(start_session):
            start_session(minutes)
        else:
            self._controller.set_feature_enabled("focus", True)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._session_row.setDirection(QBoxLayout.LeftToRight)

    def _on_dim_changed(self, value: int) -> None:
        self._dim_value.setText(f'{value}%')
        if not self._dim_slider.isSliderDown():
            self._commit_dim()

    def _commit_dim(self) -> None:
        level = round(self._dim_slider.value() * _FOCUS_DIM_MAX / 100)
        self._controller.set_focus_dim_level(level)

    def render(self, state) -> None:
        enabled = bool(first_state_value(state, "focus.enabled", default=False))
        level = int(first_state_value(state, "focus.dim_level", default=150))
        available = bool(first_state_value(state, "capabilities.focus_available", default=True))
        percent = round(level * 100 / _FOCUS_DIM_MAX)
        if not self._dim_slider.isSliderDown():
            with QSignalBlocker(self._dim_slider):
                self._dim_slider.setValue(percent)
            self._dim_value.setText(f"{percent}%")
        self._start_button.setText("结束专注" if enabled else "开始专注")
        self._start_button.setAccessibleName(self._start_button.text())
        self._start_button.setEnabled(available or enabled)
        self._duration_combo.setEnabled(available and not enabled)
        status = StatusPresenter.project(state).focus
        end = first_state_value(state, 'focus.session_ends_at')
        if enabled:
            timing = f'预计 {end.astimezone().strftime("%H:%M")} 结束' if end is not None else '持续开启，可随时结束'
            self._session_status.setText(f'{status.detail} · {timing}')
        else:
            self._session_status.setText('选择时长后开始；结束专注后恢复原来的显示。')
        self._dim_slider.setEnabled(available)
