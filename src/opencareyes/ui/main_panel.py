"""OpenCareEyes v0.2 main window with Soft Fluent side navigation."""

from __future__ import annotations

import os

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QIcon, QKeySequence, QPalette, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from opencareyes.constants import ICONS_DIR, STYLES_DIR
from opencareyes.ui.automation_page import AutomationPage
from opencareyes.ui.blue_light_page import BlueLightPage
from opencareyes.ui.break_page import BreakPage
from opencareyes.ui.focus_page import FocusPage
from opencareyes.ui.overview_page import OverviewPage
from opencareyes.ui.settings_page import SettingsPage
from opencareyes.ui.widgets import first_state_value


_PAGES = (
    ("总览", OverviewPage, "nav-overview.svg"),
    ("屏幕舒适度", BlueLightPage, "nav-display.svg"),
    ("休息节奏", BreakPage, "nav-breaks.svg"),
    ("专注模式", FocusPage, "nav-focus.svg"),
    ("自动化", AutomationPage, "nav-automation.svg"),
    ("设置", SettingsPage, "nav-settings.svg"),
)


class MainPanel(QWidget):
    """Top-level settings window; every page observes one ``AppState``."""

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._controller = controller
        self._applied_theme = ""
        self.setObjectName("mainPanel")
        self.setWindowTitle("OpenCareEyes")
        self.resize(920, 640)
        self.setMinimumSize(820, 580)
        self.setWindowFlags(self.windowFlags() | Qt.Window)
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self._build_ui()
        self._connect_signals()
        self._render(controller.state)

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setAttribute(Qt.WA_StyledBackground, True)
        sidebar.setFixedWidth(218)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(18, 22, 18, 18)
        sidebar_layout.setSpacing(14)

        brand = QLabel("OpenCareEyes")
        brand.setObjectName("brandTitle")
        brand.setAccessibleName("OpenCareEyes 主导航")
        subtitle = QLabel("让屏幕更舒适")
        subtitle.setObjectName("brandSubtitle")
        sidebar_layout.addWidget(brand)
        sidebar_layout.addWidget(subtitle)

        self._navigation = QListWidget()
        self._navigation.setObjectName("navigation")
        self._navigation.setFrameShape(QFrame.NoFrame)
        self._navigation.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._navigation.setAccessibleName("页面导航")
        self._navigation.setIconSize(QSize(20, 20))
        for index, (label, _, icon_name) in enumerate(_PAGES):
            item = QListWidgetItem(label)
            item.setIcon(QIcon(os.path.join(ICONS_DIR, icon_name)))
            item.setData(Qt.UserRole, index)
            item.setToolTip(f"Ctrl+{index + 1}")
            item.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)
            item.setSizeHint(QSize(0, 44))
            self._navigation.addItem(item)
        sidebar_layout.addWidget(self._navigation, 1)

        privacy = QLabel("本地运行 · 无账号 · 无遥测")
        privacy.setObjectName("sidebarFooter")
        privacy.setWordWrap(True)
        sidebar_layout.addWidget(privacy)
        root.addWidget(sidebar)

        content = QFrame()
        content.setObjectName("contentArea")
        content.setAttribute(Qt.WA_StyledBackground, True)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        self._message = QLabel()
        self._message.setObjectName("messageBanner")
        self._message.setWordWrap(True)
        self._message.setAccessibleName("操作提示")
        self._message.hide()
        content_layout.addWidget(self._message)
        self._message_timer = QTimer(self)
        self._message_timer.setSingleShot(True)
        self._message_timer.setInterval(6000)
        self._message_timer.timeout.connect(self._message.hide)

        self._stack = QStackedWidget()
        self._stack.setObjectName("pageStack")
        self._pages = []
        for _, page_class, _ in _PAGES:
            page = page_class(self._controller)
            self._pages.append(page)
            self._stack.addWidget(page)
        content_layout.addWidget(self._stack, 1)
        root.addWidget(content, 1)

        self._navigation.currentRowChanged.connect(self._stack.setCurrentIndex)
        self._navigation.setCurrentRow(0)
        self._shortcuts = []
        for index in range(len(_PAGES)):
            shortcut = QShortcut(QKeySequence(f"Ctrl+{index + 1}"), self)
            shortcut.activated.connect(lambda page=index: self._navigation.setCurrentRow(page))
            self._shortcuts.append(shortcut)

    def _connect_signals(self) -> None:
        self._controller.state_changed.connect(self._render)
        failed = getattr(self._controller, "operation_failed", None)
        if failed is not None:
            failed.connect(self._show_error)
        notification = getattr(self._controller, "notification_requested", None)
        if notification is not None:
            notification.connect(self._show_notification)

    def _render(self, state) -> None:
        theme = str(first_state_value(state, "general.theme", default="system"))
        self.apply_theme(theme)

    def apply_theme(self, theme: str) -> None:
        resolved = theme
        if theme == "system":
            app = QApplication.instance()
            if app is not None:
                window = app.palette().color(QPalette.Window)
                resolved = "dark" if window.lightness() < 128 else "light"
            else:
                resolved = "light"
        if resolved == self._applied_theme:
            return
        path = os.path.join(STYLES_DIR, f"{resolved}.qss")
        try:
            with open(path, "r", encoding="utf-8") as stylesheet:
                app = QApplication.instance()
                if app is not None:
                    app.setStyleSheet(stylesheet.read())
                    self._applied_theme = resolved
        except OSError:
            # A missing optional theme must not prevent the settings window opening.
            return

    def _show_error(self, code: str, message: str) -> None:
        self._message.setProperty("kind", "error")
        self._message.setText(f"操作未完成：{message}")
        self._message.style().unpolish(self._message)
        self._message.style().polish(self._message)
        self._message.show()
        self._message_timer.start()

    def _show_notification(self, title: str, message: str) -> None:
        self._message.setProperty("kind", "info")
        self._message.setText(f"{title}：{message}")
        self._message.style().unpolish(self._message)
        self._message.style().polish(self._message)
        self._message.show()
        self._message_timer.start()

    def show_page(self, name: str) -> None:
        """Open a named page; used by tray menu shortcuts."""

        normalized = name.strip()
        for index, (label, _, _) in enumerate(_PAGES):
            if normalized == label:
                self._navigation.setCurrentRow(index)
                break
        self.show_and_activate()

    def show_and_activate(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def toggle_visible(self) -> None:
        if self.isVisible() and not self.isMinimized():
            self.hide()
        else:
            self.show_and_activate()

    def closeEvent(self, event) -> None:
        """Keep the app in the tray when the settings window is closed."""

        event.ignore()
        self.hide()
