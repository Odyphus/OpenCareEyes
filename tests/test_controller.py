"""Tests for immutable state and controller-only feature writes."""

from dataclasses import FrozenInstanceError
import sys

import pytest
from PySide6.QtCore import QCoreApplication, QObject, Signal
from PySide6.QtTest import QSignalSpy

from opencareyes.config.settings import Settings
from opencareyes.controller import AppController
from opencareyes.core.break_reminder import BreakReminder


@pytest.fixture(scope="module")
def qapp():
    return QCoreApplication.instance() or QCoreApplication(sys.argv)


class MemoryStore:
    def __init__(self):
        self.values = {}

    def value(self, key, default=None, type=None):
        value = self.values.get(key, default)
        if type is not None and value is not None:
            return type(value)
        return value

    def setValue(self, key, value):
        self.values[key] = value

    def allKeys(self):
        return list(self.values)

    def sync(self):
        pass

    def clear(self):
        self.values.clear()


class FailingSyncStore(MemoryStore):
    def __init__(self):
        super().__init__()
        self.fail_next_sync = False

    def sync(self):
        if self.fail_next_sync:
            self.fail_next_sync = False
            raise OSError("设置保存失败")


class FakeHotkeys(QObject):
    registration_failed = Signal(str, str)
    callback_failed = Signal(str, str)

    def __init__(self):
        super().__init__()
        self.mappings = []

    def replace_all(self, mapping):
        self.mappings.append(tuple(sorted(mapping)))
        return True


class FakeDisplayEffect:
    def __init__(self):
        self.enabled = False
        self.level = None
        self.fail_enable = False

    def enable(self, level=None):
        if self.fail_enable:
            raise RuntimeError("device rejected operation")
        self.enabled = True
        self.level = level

    def disable(self):
        self.enabled = False

    def set_temperature(self, value):
        self.level = value

    def set_brightness(self, value):
        self.level = value


class FakeFocus(FakeDisplayEffect):
    def set_dim_level(self, value):
        self.level = value


class FakeScheduler(QObject):
    next_event_changed = Signal(object)
    running_changed = Signal(bool)
    manual_override_changed = Signal(bool)
    error = Signal(str, str)

    def __init__(self):
        super().__init__()
        self.running = False
        self.next_event = None
        self.next_event_at = None
        self.manual_override = False
        self.callback = None

    def set_state_callback(self, callback):
        self.callback = callback

    def start(self):
        self.running = True
        self.running_changed.emit(True)

    def stop(self):
        self.running = False
        self.running_changed.emit(False)

    def reschedule(self):
        pass

    def set_manual_override(self, value):
        self.manual_override = value
        self.manual_override_changed.emit(value)


@pytest.fixture
def controller(qapp):
    settings = Settings(MemoryStore())
    blue_filter = FakeDisplayEffect()
    dimmer = FakeDisplayEffect()
    reminder = BreakReminder()
    focus = FakeFocus()
    scheduler = FakeScheduler()
    instance = AppController(
        settings,
        blue_filter,
        dimmer,
        reminder,
        focus,
        scheduler,
    )
    yield instance, settings, blue_filter, dimmer, reminder, focus, scheduler
    reminder.stop()


def test_app_state_is_immutable(controller):
    instance, *_ = controller
    with pytest.raises(FrozenInstanceError):
        instance.state.display.filter_enabled = True


def test_controller_updates_service_settings_and_snapshot(controller):
    instance, settings, blue_filter, *_ = controller
    spy = QSignalSpy(instance.state_changed)

    assert instance.set_filter_enabled(True) is True

    assert blue_filter.enabled is True
    assert settings.filter_enabled is True
    assert instance.state.display.filter_enabled is True
    assert spy.count() == 1


def test_skip_break_is_runtime_only_and_immediate(controller, monkeypatch):
    instance, _settings, _blue_filter, _dimmer, reminder, *_ = controller
    reminder.start()
    assert reminder.start_break_now("short") is True
    assert reminder.phase == "resting"

    def unexpected_call(*_args, **_kwargs):
        raise AssertionError("runtime-only break exit touched persistence or effects")

    monkeypatch.setattr(instance, "_sync_settings_checked", unexpected_call)
    monkeypatch.setattr(instance, "_reconcile_effects", unexpected_call)
    monkeypatch.setattr(
        instance,
        "_apply_break_configuration_from_settings",
        unexpected_call,
    )
    monkeypatch.setattr(instance, "_restore_pause_deadline", unexpected_call)

    assert instance.skip_break() is True
    assert reminder.phase == "working"
    assert reminder.is_on_break is False
    assert instance.state.breaks.phase == "working"


def test_failed_service_write_is_visible_and_not_persisted(controller):
    instance, settings, blue_filter, *_ = controller
    blue_filter.fail_enable = True
    spy = QSignalSpy(instance.operation_failed)
    state_spy = QSignalSpy(instance.state_changed)

    assert instance.set_filter_enabled(True) is False

    assert settings.filter_enabled is False
    assert instance.state.display.filter_enabled is False
    assert spy.count() == 1
    assert spy.at(0)[0] == "filter_toggle"
    assert spy.at(0)[1] == "显示效果未能应用，请重试。"
    assert "device rejected operation" not in spy.at(0)[1]
    assert state_spy.count() == 1
    assert state_spy.at(0)[0].display.filter_enabled is False


def test_hotkey_sync_failure_restores_settings_and_native_mapping(qapp):
    store = FailingSyncStore()
    settings = Settings(store)
    hotkeys = FakeHotkeys()
    controller = AppController(settings, hotkeys=hotkeys)
    old_filter = settings.hotkey_filter
    old_mapping = tuple(
        sorted(
            (
                settings.hotkey_filter,
                settings.hotkey_break,
                settings.hotkey_dimmer,
                settings.hotkey_focus,
            )
        )
    )
    failures = QSignalSpy(controller.operation_failed)
    store.fail_next_sync = True

    assert controller.set_hotkeys({"filter": "ctrl+alt+9"}) is False

    assert settings.hotkey_filter == old_filter
    assert hotkeys.mappings[-2] != old_mapping
    assert hotkeys.mappings[-1] == old_mapping
    assert failures.count() == 1
    assert failures.at(0)[0] == "hotkey"
    assert failures.at(0)[1] == (
        "快捷键设置未能保存，请检查组合键是否被占用。"
    )


def test_restore_failure_rolls_back_persisted_enabled_state(qapp):
    settings = Settings(MemoryStore())
    settings.filter_enabled = True
    blue_filter = FakeDisplayEffect()
    blue_filter.fail_enable = True
    instance = AppController(settings, blue_filter=blue_filter)
    failure_spy = QSignalSpy(instance.operation_failed)
    state_spy = QSignalSpy(instance.state_changed)

    assert instance.state.display.filter_enabled is True
    assert instance.restore() is False

    assert blue_filter.enabled is False
    assert settings.filter_enabled is False
    assert instance.state.display.filter_enabled is False
    assert failure_spy.count() == 1
    assert failure_spy.at(0)[0] == "restore_filter"
    assert state_spy.count() == 1
    assert state_spy.at(0)[0].display.filter_enabled is False


def test_global_pause_preserves_preferences_and_restores_services(controller):
    instance, settings, blue_filter, dimmer, reminder, *_ = controller
    settings.filter_enabled = True
    settings.dimmer_enabled = True
    settings.break_enabled = True
    assert instance.restore() is True
    assert blue_filter.enabled and dimmer.enabled and reminder.enabled

    assert instance.pause_all() is True
    assert instance.state.global_pause.active is True
    assert settings.filter_enabled and settings.dimmer_enabled and settings.break_enabled
    assert not blue_filter.enabled and not dimmer.enabled and not reminder.enabled

    assert instance.resume_all() is True
    assert instance.state.global_pause.active is False
    assert blue_filter.enabled and dimmer.enabled and reminder.enabled


def test_schedule_boundary_applies_profiles_without_recreating_manual_override(
    controller,
):
    instance, settings, blue_filter, dimmer, *_, scheduler = controller
    scheduler.running = True

    assert instance.apply_display_profile("reading") is True
    assert scheduler.manual_override is True

    scheduler.set_manual_override(False)
    scheduler.callback(True)
    assert settings.current_preset == "night"
    assert settings.color_temperature == 3400
    assert settings.dim_level == 50
    assert blue_filter.enabled is True
    assert blue_filter.level == 3400
    assert dimmer.enabled is True
    assert dimmer.level == 50
    assert scheduler.manual_override is False

    scheduler.callback(False)
    assert settings.current_preset == "office"
    assert settings.color_temperature == 5500
    assert settings.dim_level == 0
    assert blue_filter.enabled is True
    assert blue_filter.level == 5500
    assert dimmer.enabled is False
    assert scheduler.manual_override is False


def test_fixed_schedule_event_labels_match_applied_profiles():
    from opencareyes.ui.widgets import schedule_event_description

    assert schedule_event_description("on") == "切换到夜间方案"
    assert schedule_event_description("off") == "切换到日间方案"


def test_onboarding_completion_is_published(controller):
    instance, settings, *_ = controller
    assert instance.state.general.onboarding_completed is False
    assert instance.complete_onboarding() is True
    assert settings.onboarding_completed is True
    assert instance.state.general.onboarding_completed is True


def test_break_countdown_display_is_published(controller):
    instance, settings, *_ = controller

    assert instance.set_break_countdown_display("floating") is True

    assert settings.break_countdown_display == "floating"
    assert instance.state.breaks.countdown_display == "floating"


def test_invalid_break_countdown_display_is_rejected(controller):
    instance, settings, *_ = controller
    spy = QSignalSpy(instance.operation_failed)

    assert instance.set_break_countdown_display("always") is False

    assert settings.break_countdown_display == "tray"
    assert spy.count() == 1


def test_invalid_commands_expose_fixed_chinese_messages(controller):
    instance, *_ = controller
    failures = QSignalSpy(instance.operation_failed)
    cases = (
        (
            lambda: instance.set_feature_enabled("private-feature", True),
            "不支持该功能设置。",
        ),
        (
            lambda: instance.set_break_reminder_style("private-style"),
            "不支持该休息提醒方式。",
        ),
        (
            lambda: instance.set_break_countdown_display("private-mode"),
            "不支持该倒计时显示方式。",
        ),
        (
            lambda: instance.set_schedule(False, mode="private-mode"),
            "请选择固定时间或日出日落自动化。",
        ),
        (
            lambda: instance.set_schedule(False, mode="fixed", latitude=31.2),
            "纬度和经度必须同时填写。",
        ),
        (
            lambda: instance.set_schedule(
                False,
                mode="fixed",
                latitude=91,
                longitude=0,
            ),
            "纬度必须在 -90 到 90 之间。",
        ),
        (
            lambda: instance.set_schedule(
                False,
                mode="fixed",
                latitude=0,
                longitude=181,
            ),
            "经度必须在 -180 到 180 之间。",
        ),
        (
            lambda: instance.set_schedule(False, mode="fixed", on_time="25:00"),
            "开启时间格式无效，请使用 HH:MM。",
        ),
        (
            lambda: instance.set_schedule(False, mode="fixed", off_time="25:00"),
            "关闭时间格式无效，请使用 HH:MM。",
        ),
        (
            lambda: instance.set_schedule(False, mode="fixed", days=()),
            "请至少选择一个有效执行日。",
        ),
        (
            lambda: instance.set_schedule(True, mode="sun"),
            "请先设置自动化位置。",
        ),
        (
            lambda: instance.set_schedule(
                False,
                mode="fixed",
                day_profile="private-profile",
            ),
            "请选择有效的日间和夜间显示方案。",
        ),
        (
            lambda: instance.set_schedule(
                False,
                mode="fixed",
                sunrise_offset=121,
            ),
            "日出和日落偏移必须在 -120 到 120 分钟之间。",
        ),
        (
            lambda: instance.pause_all(minutes=5, until_next_schedule=True),
            "暂停方式只能选择时长或直到下次自动切换。",
        ),
        (
            lambda: instance.pause_all(minutes=0),
            "暂停时长必须大于 0 分钟。",
        ),
        (
            lambda: instance.pause_all(until_next_schedule=True),
            "自动化未运行，无法暂停到下次自动切换。",
        ),
        (
            lambda: instance.start_focus_session(0),
            "专注时长必须大于 0 分钟。",
        ),
        (
            lambda: instance.set_theme("private-theme"),
            "请选择跟随系统、亮色或暗色主题。",
        ),
        (
            lambda: instance.set_motion_mode("private-motion"),
            "请选择跟随系统、标准或减少动画。",
        ),
        (
            instance.resume_breaks_for_current_context,
            "智能免打扰当前不可用。",
        ),
        (
            lambda: instance.set_location(91, 0),
            "纬度或经度超出有效范围。",
        ),
        (
            lambda: instance.set_hotkeys(
                {"private-action": "ctrl+alt+n"}
            ),
            "不支持该快捷键功能。",
        ),
    )

    for action, expected in cases:
        previous_count = failures.count()
        assert action() is False
        assert failures.count() == previous_count + 1
        assert failures.at(previous_count)[1] == expected


def test_fail_hides_unknown_backend_detail_and_absolute_path(controller):
    instance, *_ = controller
    failures = QSignalSpy(instance.operation_failed)
    private_path = r"C:\Users\Alice\Private\native-state.bin"

    instance._fail(
        "future_native_failure",
        PermissionError(13, "private backend detail", private_path),
    )
    instance._fail(
        "filter_toggle_rollback",
        RuntimeError(f"rollback failed at {private_path}"),
    )

    assert failures.at(0) == [
        "future_native_failure",
        "当前操作未能完成，请重试。",
    ]
    assert failures.at(1) == [
        "filter_toggle_rollback",
        "操作回滚不完整，请重启 OpenCareEyes 后检查设置。",
    ]
    assert all(private_path not in failures.at(index)[1] for index in range(2))
    assert all("private backend detail" not in failures.at(index)[1] for index in range(2))


def test_diagnostics_export_failure_hides_target_path(
    controller,
    monkeypatch,
):
    instance, *_ = controller
    failures = QSignalSpy(instance.operation_failed)
    private_path = r"C:\Users\Alice\Private\diagnostics.zip"

    def fail_export(destination, _state):
        raise PermissionError(13, "private export detail", str(destination))

    monkeypatch.setattr("opencareyes.controller.write_diagnostics", fail_export)

    assert instance.export_diagnostics(private_path) is False
    assert failures.count() == 1
    assert failures.at(0) == [
        "diagnostics_export",
        "诊断信息未能导出，请检查目标文件夹权限后重试。",
    ]
    assert private_path not in failures.at(0)[1]
    assert "private export detail" not in failures.at(0)[1]


def test_strict_break_rejects_snooze_from_every_entry_point(controller):
    instance, settings, _, _, reminder, *_ = controller
    spy = QSignalSpy(instance.operation_failed)

    assert instance.set_force_break(True) is True
    assert instance.snooze_break(5) is False

    assert settings.force_break is True
    assert reminder.force_break is True
    assert spy.count() == 1
