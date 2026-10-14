"""Focused tests for v0.4 automation controls and privacy boundaries."""

from PySide6.QtCore import QObject, Signal

from opencareyes.state import (
    AppState,
    BreakState,
    EffectivePolicyState,
    FeatureRuntimeState,
)
from opencareyes.ui.automation_page import (
    AutomationPage,
    QFileDialog,
    _basename_app_id,
)
from opencareyes.ui.widgets import (
    display_backend_description,
    feature_description,
    schedule_event_description,
    suppression_reason_description,
)


class FakeController(QObject):
    state_changed = Signal(object)

    def __init__(self):
        super().__init__()
        self.state = AppState()
        self.rules = []
        self.schedule_call = None
        self.location_calls = 0

    def set_schedule(
        self,
        enabled,
        *,
        mode=None,
        latitude=None,
        longitude=None,
        city=None,
        on_time=None,
        off_time=None,
        days=None,
        day_profile=None,
        night_profile=None,
        sunrise_offset=None,
        sunset_offset=None,
    ):
        self.schedule_call = {
            "enabled": enabled,
            "mode": mode,
            "latitude": latitude,
            "longitude": longitude,
            "city": city,
            "on_time": on_time,
            "off_time": off_time,
            "days": days,
            "day_profile": day_profile,
            "night_profile": night_profile,
            "sunrise_offset": sunrise_offset,
            "sunset_offset": sunset_offset,
        }
        return True

    def set_location(self, *_args):
        self.location_calls += 1
        return True

    def upsert_app_rule(self, rule):
        self.rules.append(rule)
        return True

    def remove_app_rule(self, _app_id):
        return True

    def set_smart_pause_enabled(self, _enabled):
        return True

    def set_fullscreen_pause_enabled(self, _enabled):
        return True

    def set_natural_rest_enabled(self, _enabled):
        return True

    def resume_breaks_for_current_context(self):
        return True


def test_basename_helper_never_returns_a_full_path():
    assert _basename_app_id(r"C:\Program Files\Demo\APP.EXE") == "app.exe"
    assert _basename_app_id("not-a-program.txt") == ""


def test_application_rule_headers_explain_suppression_semantics(qtbot):
    page = AutomationPage(FakeController())
    qtbot.addWidget(page)

    labels = [
        page._rules_table.horizontalHeaderItem(column).text()
        for column in range(3)
    ]
    assert labels == ["应用", "暂停休息", "隐藏专注"]


def test_internal_status_codes_have_chinese_labels_and_unknown_fallbacks():
    assert display_backend_description("gamma_ramp") == "Windows 显示色彩调节"
    assert display_backend_description("future_backend") == "系统显示接口"
    assert schedule_event_description("future_event") == "执行自动化切换"
    assert suppression_reason_description("session_locked") == "锁屏"
    assert suppression_reason_description("system_suspended") == "系统睡眠"
    assert suppression_reason_description("app:powerpnt.exe") == "应用 powerpnt.exe"
    assert suppression_reason_description("future_reason") == "未知情境"
    assert feature_description("future_feature") == "未知功能"


def test_application_rule_accessible_names_use_chinese_feature_labels(qtbot):
    page = AutomationPage(FakeController())
    qtbot.addWidget(page)
    page._render_app_rules(
        [
            {
                "app_id": "powerpnt.exe",
                "breaks": True,
                "focus": True,
                "filter": False,
                "dimmer": False,
            }
        ]
    )

    assert [
        page._rules_table.cellWidget(0, column).accessibleName()
        for column in range(1, 3)
    ] == [
        "powerpnt.exe · 暂停休息",
        "powerpnt.exe · 隐藏专注",
    ]


def test_safety_suppression_never_offers_context_override(qtbot):
    page = AutomationPage(FakeController())
    qtbot.addWidget(page)

    page.render(
        AppState(
            breaks=BreakState(enabled=True),
            effective_policy=EffectivePolicyState(
                breaks=FeatureRuntimeState(
                    desired_enabled=True,
                    suppressed_by=("fullscreen",),
                    resume_condition="退出全屏后恢复",
                )
            ),
        )
    )
    assert not page._resume_context_button.isHidden()

    page.render(
        AppState(
            breaks=BreakState(enabled=True),
            effective_policy=EffectivePolicyState(
                breaks=FeatureRuntimeState(
                    desired_enabled=True,
                    suppressed_by=("session_locked",),
                    resume_condition="解锁后恢复",
                )
            ),
        )
    )
    assert page._resume_context_button.isHidden()


def test_choose_exe_passes_only_lowercase_basename(qtbot, monkeypatch):
    controller = FakeController()
    page = AutomationPage(controller)
    qtbot.addWidget(page)
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        lambda *_args, **_kwargs: (r"C:\Private\Tools\DEMO.EXE", ""),
    )

    page._choose_app()

    assert controller.rules[-1]["app_id"] == "demo.exe"
    assert "Private" not in str(controller.rules[-1])


def test_context_page_has_no_schedule_or_display_controls(qtbot):
    from PySide6.QtWidgets import QComboBox, QSlider, QTimeEdit
    controller = FakeController()
    page = AutomationPage(controller)
    qtbot.addWidget(page)
    assert page.findChildren(QComboBox) == []
    assert page.findChildren(QTimeEdit) == []
    assert page.findChildren(QSlider) == []
    assert controller.schedule_call is None
    assert page._rules_table.columnCount() == 4


def test_editing_break_rule_preserves_legacy_data_without_exposing_dimming(qtbot):
    controller = FakeController()
    page = AutomationPage(controller)
    qtbot.addWidget(page)
    page._render_app_rules([{
        'app_id': 'demo.exe', 'breaks': True, 'focus': True,
        'filter': True, 'dimmer': True,
    }])
    page._rules_table.cellWidget(0, 1).setChecked(False)
    assert controller.rules[-1] == {
        'app_id': 'demo.exe', 'breaks': False, 'focus': True,
        'filter': True, 'dimmer': True,
    }
