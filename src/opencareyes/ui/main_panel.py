"""OpenCareEyes v0.2 main window with Soft Fluent side navigation."""

from __future__ import annotations

import os

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QIcon, QKeySequence, QShortcut
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

from opencareyes.constants import ICONS_DIR
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
        # Pages scroll independently, so a compact top-level minimum is safer
        # on 200% DPI laptops than forcing the window below the work area.
        self.setMinimumSize(480, 320)
        self.setWindowFlags(self.windowFlags() | Qt.Window)
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self._build_ui()
        self._connect_signals()
        self._render(controller.state)

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._sidebar = QFrame()
        self._sidebar.setObjectName("sidebar")
        self._sidebar.setAttribute(Qt.WA_StyledBackground, True)
        self._sidebar.setFixedWidth(218)
        sidebar_layout = QVBoxLayout(self._sidebar)
        sidebar_layout.setContentsMargins(18, 22, 18, 18)
        sidebar_layout.setSpacing(14)

        self._brand = QLabel("OpenCareEyes")
        self._brand.setObjectName("brandTitle")
        self._brand.setAccessibleName("OpenCareEyes 主导航")
        self._subtitle = QLabel("让屏幕更舒适")
        self._subtitle.setObjectName("brandSubtitle")
        sidebar_layout.addWidget(self._brand)
        sidebar_layout.addWidget(self._subtitle)

        self._navigation = QListWidget()
        self._navigation.setObjectName("navigation")
        self._navigation.setFrameShape(QFrame.NoFrame)
        self._navigation.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._navigation.setAccessibleName("页面导航")
        self._navigation.setIconSize(QSize(20, 20))
        self._nav_labels = []
        for index, (label, _, icon_name) in enumerate(_PAGES):
            item = QListWidgetItem(label)
            item.setIcon(QIcon(os.path.join(ICONS_DIR, icon_name)))
            item.setData(Qt.UserRole, index)
            item.setToolTip(f"Ctrl+{index + 1}")
            item.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)
            item.setSizeHint(QSize(0, 44))
            item.setData(Qt.AccessibleTextRole, label)
            self._navigation.addItem(item)
            self._nav_labels.append(label)
        sidebar_layout.addWidget(self._navigation, 1)

        self._privacy = QLabel("本地运行 · 无账号 · 无遥测")
        self._privacy.setObjectName("sidebarFooter")
        self._privacy.setWordWrap(True)
        sidebar_layout.addWidget(self._privacy)
        root.addWidget(self._sidebar)

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
        self._pages = [None] * len(_PAGES)
        for _ in _PAGES:
            self._stack.addWidget(QWidget())
        self._ensure_page(0)
        content_layout.addWidget(self._stack, 1)
        root.addWidget(content, 1)

        self._navigation.currentRowChanged.connect(self._select_page)
        self._navigation.setCurrentRow(0)
        self._shortcuts = []
        for index in range(len(_PAGES)):
            shortcut = QShortcut(QKeySequence(f"Ctrl+{index + 1}"), self)
            shortcut.activated.connect(lambda page=index: self._navigation.setCurrentRow(page))
            self._shortcuts.append(shortcut)
        self._update_responsive_layout()

    def _ensure_page(self, index: int) -> QWidget:
        page = self._pages[index]
        if page is not None:
            return page

        placeholder = self._stack.widget(index)
        _, page_class, _ = _PAGES[index]
        page = page_class(self._controller)
        self._stack.removeWidget(placeholder)
        placeholder.deleteLater()
        self._stack.insertWidget(index, page)
        self._pages[index] = page
        return page

    def _select_page(self, index: int) -> None:
        if not 0 <= index < len(_PAGES):
            return
        self._stack.setCurrentWidget(self._ensure_page(index))

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
        app = QApplication.instance()
        if app is None:
            return
        applier = getattr(app, "apply_theme", None)
        resolved = applier(theme) if callable(applier) else theme
        self._applied_theme = str(resolved)

    def _update_responsive_layout(self) -> None:
        compact = self.width() < 880
        self._sidebar.setFixedWidth(82 if compact else 218)
        self._brand.setVisible(not compact)
        self._subtitle.setVisible(not compact)
        self._privacy.setVisible(not compact)
        for index, label in enumerate(self._nav_labels):
            item = self._navigation.item(index)
            item.setText("" if compact else label)
            item.setToolTip(
                f"{label} · Ctrl+{index + 1}" if compact else f"Ctrl+{index + 1}"
            )

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_responsive_layout()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._fit_available_geometry()

    def _fit_available_geometry(self) -> None:
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry().adjusted(8, 8, -8, -8)
        width = min(self.width(), max(self.minimumWidth(), area.width()))
        height = min(self.height(), max(self.minimumHeight(), area.height()))
        if self.size() != QSize(width, height):
            self.resize(width, height)
        geometry = self.frameGeometry()
        x = min(max(geometry.x(), area.left()), area.right() - geometry.width() + 1)
        y = min(max(geometry.y(), area.top()), area.bottom() - geometry.height() + 1)
        if geometry.x() != x or geometry.y() != y:
            self.move(x, y)

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


class DeferredMainPanel:
    """Create the settings window only when the user asks to see it."""

    def __init__(self, controller):
        self._controller = controller
        self._panel: MainPanel | None = None

    @property
    def widget(self) -> MainPanel:
        if self._panel is None:
            self._panel = MainPanel(self._controller)
        return self._panel

    @property
    def is_created(self) -> bool:
        return self._panel is not None

    def show_and_activate(self) -> None:
        self.widget.show_and_activate()

    def toggle_visible(self) -> None:
        if self._panel is None:
            self.show_and_activate()
            return
        self._panel.toggle_visible()

    def show_page(self, name: str) -> None:
        self.widget.show_page(name)
