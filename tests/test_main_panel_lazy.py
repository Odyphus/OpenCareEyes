from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

import opencareyes.ui.main_panel as main_panel_module  # noqa: E402


class _Controller(QObject):
    state_changed = Signal(object)
    operation_failed = Signal(str, str)
    notification_requested = Signal(str, str)

    def __init__(self):
        super().__init__()
        self.state = SimpleNamespace(general=SimpleNamespace(theme="light"))


def test_main_panel_builds_pages_only_when_selected(monkeypatch):
    app = QApplication.instance() or QApplication([])
    created = [0, 0, 0]

    def page_class(index: int):
        class Page(QWidget):
            def __init__(self, controller):
                super().__init__()
                created[index] += 1

        return Page

    pages = tuple(
        (f"页面 {index}", page_class(index), "missing.svg") for index in range(3)
    )
    monkeypatch.setattr(main_panel_module, "_PAGES", pages)

    panel = main_panel_module.MainPanel(_Controller())
    assert created == [1, 0, 0]
    assert panel._pages[0] is not None
    assert panel._pages[1:] == [None, None]

    panel._navigation.setCurrentRow(1)
    app.processEvents()
    assert created == [1, 1, 0]
    panel._navigation.setCurrentRow(0)
    panel._navigation.setCurrentRow(1)
    app.processEvents()
    assert created == [1, 1, 0]

    panel.show_page("页面 2")
    app.processEvents()
    assert created == [1, 1, 1]
    panel.close()


def test_deferred_main_panel_is_created_on_first_show(monkeypatch):
    created = []

    class Panel:
        def __init__(self, controller):
            created.append(controller)
            self.visible = False

        def show_and_activate(self):
            self.visible = True

        def toggle_visible(self):
            self.visible = not self.visible

        def show_page(self, name):
            self.page = name

    monkeypatch.setattr(main_panel_module, "MainPanel", Panel)
    controller = object()
    panel = main_panel_module.DeferredMainPanel(controller)

    assert panel.is_created is False
    panel.show_and_activate()
    assert panel.is_created is True
    assert created == [controller]
    panel.toggle_visible()
    panel.show_page("设置")
    assert created == [controller]
    assert panel.widget.page == "设置"
