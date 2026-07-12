"""Small reusable widgets shared by the OpenCareEyes settings pages.

The module intentionally contains no application logic.  Pages read the immutable
``AppState`` and send commands to ``AppController``; these helpers only keep the
visual hierarchy and accessibility metadata consistent.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


def state_value(state: object, path: str, default: Any = None) -> Any:
    """Read a dotted path from dataclasses, mappings, or simple namespaces."""

    value: Any = state
    for name in path.split("."):
        if value is None:
            return default
        if isinstance(value, Mapping):
            value = value.get(name, default)
        else:
            value = getattr(value, name, default)
    return default if value is None else value


def first_state_value(state: object, *paths: str, default: Any = None) -> Any:
    """Return the first state value present among several compatible paths."""

    sentinel = object()
    for path in paths:
        value = state_value(state, path, sentinel)
        if value is not sentinel and value is not None:
            return value
    return default


def format_duration(seconds: int | float | None, fallback: str = "--") -> str:
    """Format a duration for compact UI labels."""

    if seconds is None:
        return fallback
    seconds = max(0, int(seconds))
    if seconds >= 3600:
        hours, remainder = divmod(seconds, 3600)
        minutes = remainder // 60
        return f"{hours} 小时 {minutes} 分" if minutes else f"{hours} 小时"
    minutes, secs = divmod(seconds, 60)
    return f"{minutes}:{secs:02d}"


def temperature_description(kelvin: int) -> str:
    """Translate a Kelvin value into a calm, non-medical description."""

    if kelvin <= 3200:
        return "暖色"
    if kelvin <= 4300:
        return "偏暖"
    if kelvin <= 5600:
        return "自然"
    return "清爽"


def schedule_event_description(event: str) -> str:
    """Return the user-facing display-profile action for a schedule boundary."""

    return {
        "sunset": "切换到夜间方案",
        "sunrise": "切换到日间方案",
        "on": "切换到夜间方案",
        "off": "切换到日间方案",
        "enable": "切换到夜间方案",
        "disable": "切换到日间方案",
    }.get(event, event)


def set_accessible(widget: QWidget, name: str, description: str = "") -> QWidget:
    widget.setAccessibleName(name)
    if description:
        widget.setAccessibleDescription(description)
    return widget


class PageHeader(QWidget):
    """Consistent title and supporting copy used at the top of each page."""

    def __init__(self, title: str, description: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("pageHeader")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 8)
        layout.setSpacing(4)

        title_label = QLabel(title)
        title_label.setObjectName("pageTitle")
        title_label.setAccessibleName(f"页面标题：{title}")
        layout.addWidget(title_label)

        description_label = QLabel(description)
        description_label.setObjectName("pageDescription")
        description_label.setWordWrap(True)
        layout.addWidget(description_label)


class Card(QFrame):
    """Soft Fluent content card with an optional heading and description."""

    def __init__(
        self,
        title: str = "",
        description: str = "",
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setObjectName("card")
        self.setFrameShape(QFrame.NoFrame)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(20, 18, 20, 18)
        self.body.setSpacing(12)

        if title:
            heading = QLabel(title)
            heading.setObjectName("cardTitle")
            heading.setAccessibleName(f"分区：{title}")
            self.body.addWidget(heading)
        if description:
            copy = QLabel(description)
            copy.setObjectName("cardDescription")
            copy.setWordWrap(True)
            self.body.addWidget(copy)


class StatusCard(Card):
    """Compact summary card with a status badge and a primary value."""

    def __init__(self, title: str, parent: QWidget | None = None):
        super().__init__(parent=parent)
        heading_row = QHBoxLayout()
        heading_row.setSpacing(8)
        heading = QLabel(title)
        heading.setObjectName("statusCardTitle")
        self.badge = QLabel("未启用")
        self.badge.setObjectName("statusBadge")
        heading_row.addWidget(heading)
        heading_row.addStretch()
        heading_row.addWidget(self.badge)
        self.body.addLayout(heading_row)

        self.value = QLabel("--")
        self.value.setObjectName("statusValue")
        self.value.setWordWrap(True)
        self.body.addWidget(self.value)

        self.detail = QLabel("")
        self.detail.setObjectName("statusDetail")
        self.detail.setWordWrap(True)
        self.body.addWidget(self.detail)

    def set_status(
        self,
        enabled: bool,
        value: str,
        detail: str = "",
        active_text: str = "运行中",
        inactive_text: str = "未启用",
    ) -> None:
        self.badge.setText(active_text if enabled else inactive_text)
        self.badge.setProperty("active", enabled)
        self.badge.style().unpolish(self.badge)
        self.badge.style().polish(self.badge)
        self.value.setText(value)
        self.detail.setText(detail)
        self.setAccessibleName(f"{value}，{self.badge.text()}")


class ScrollPage(QScrollArea):
    """A frameless page whose content remains usable at 200% scaling."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("scrollPage")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.content = QWidget()
        self.content.setObjectName("pageContent")
        self.layout = QVBoxLayout(self.content)
        self.layout.setContentsMargins(28, 24, 28, 28)
        self.layout.setSpacing(16)
        self.setWidget(self.content)


def refresh_property(widget: QWidget, name: str, value: Any) -> None:
    """Update a dynamic property and immediately repolish the widget."""

    if widget.property(name) == value:
        return
    widget.setProperty(name, value)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
