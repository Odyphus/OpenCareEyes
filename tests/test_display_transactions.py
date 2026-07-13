"""Revision-gated display preference transaction tests."""

from __future__ import annotations

from PySide6.QtCore import QObject, QSettings, Signal
from PySide6.QtTest import QSignalSpy

from opencareyes.application.context_coordinator import ContextCoordinator
from opencareyes.application.effect_coordinator import EffectCoordinator
from opencareyes.config.settings import Settings
from opencareyes.controller import AppController
from opencareyes.core.break_reminder import BreakReminder
from opencareyes.core.display_worker import GammaRequestToken, GammaResult
from opencareyes.domain.context import ContextSnapshot


class CountingStore:
    def __init__(self):
        self.values = {}
        self.sync_count = 0
        self.fail_sync_count = 0
        self.synced_values = []

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
        self.sync_count += 1
        if self.fail_sync_count:
            self.fail_sync_count -= 1
            raise OSError("simulated settings sync failure")
        self.synced_values.append(dict(self.values))

    def clear(self):
        self.values.clear()

    def status(self):
        return 0


class ManualGamma(QObject):
    state_changed = Signal()
    request_finished = Signal(object)
    operation_failed = Signal(str, str)

    def __init__(self):
        super().__init__()
        self.enabled = False
        self.current_temperature = 6500
        self.hdr_active = False
        self.capability_verified = True
        self.last_error_code = ""
        self.last_error_message = ""
        self._next_id = 1
        self._pending = {}
        self._last_request = None
        self._latest_completed = 0

    @property
    def pending(self):
        return bool(self._pending)

    @property
    def commit_pending(self):
        return any(
            token.purpose != "preview" for token in self._pending.values()
        )

    @property
    def preview_pending(self):
        return any(
            token.purpose == "preview" for token in self._pending.values()
        )

    @property
    def pending_target(self):
        for token in reversed(tuple(self._pending.values())):
            if token.kind == "enable":
                return True
            if token.kind == "disable":
                return False
        return None

    @property
    def last_request_id(self):
        return 0 if self._last_request is None else self._last_request.request_id

    @property
    def requests(self):
        return tuple(self._pending.values())

    def request_enable(
        self,
        temperature=6500,
        *,
        revision=0,
        purpose="commit",
    ):
        return self._reserve("enable", temperature, revision, purpose)

    def request_disable(self, *, revision=0, purpose="commit"):
        return self._reserve("disable", None, revision, purpose)

    def request_temperature(
        self,
        temperature,
        *,
        revision=0,
        purpose="commit",
    ):
        return self._reserve("temperature", temperature, revision, purpose)

    def preview_temperature(self, temperature, *, revision=0):
        return self._reserve("temperature", temperature, revision, "preview")

    def request_refresh(self, *, revision=0, purpose="system"):
        return self._reserve("refresh", None, revision, purpose)

    def refresh_screens(self, *_args):
        self.request_refresh()
        return True

    def enable(self, temperature=6500):
        self.request_enable(temperature, purpose="legacy")
        return True

    def disable(self):
        self.request_disable(purpose="legacy")
        return True

    def set_temperature(self, temperature):
        self.preview_temperature(temperature)
        return True

    def _reserve(self, kind, value, revision, purpose):
        token = GammaRequestToken(
            self._next_id,
            int(revision),
            str(kind),
            str(purpose),
            None if value is None else int(value),
        )
        self._next_id += 1
        self._pending[token.request_id] = token
        self._last_request = token
        self.state_changed.emit()
        return token

    def complete(
        self,
        token,
        *,
        success=True,
        code="",
        message="",
        hdr_active=None,
    ):
        self._pending.pop(token.request_id, None)
        superseded = token.request_id < self._latest_completed
        if not superseded:
            self._latest_completed = token.request_id
            if hdr_active is not None:
                self.hdr_active = bool(hdr_active)
            if success:
                if token.kind == "enable":
                    self.enabled = True
                    self.current_temperature = int(token.requested_value)
                elif token.kind == "disable":
                    self.enabled = False
                elif token.kind == "temperature":
                    self.current_temperature = int(token.requested_value)
                self.last_error_code = ""
                self.last_error_message = ""
            else:
                self.last_error_code = str(code or "gamma_apply_failed")
                self.last_error_message = str(message or "gamma failed")
        result = GammaResult(
            token=token,
            success=bool(success),
            superseded=superseded,
            enabled=self.enabled,
            temperature=self.current_temperature,
            hdr_active=self.hdr_active,
            capability_verified=self.capability_verified,
            code=str(code),
            message=str(message),
        )
        self.state_changed.emit()
        self.request_finished.emit(result)


class FakeDimmer:
    def __init__(self):
        self.enabled = False
        self.dim_level = 0

    def enable(self, level):
        self.enabled = True
        self.dim_level = int(level)
        return True

    def disable(self):
        self.enabled = False
        return True

    def set_brightness(self, level):
        self.dim_level = int(level)
        return True


class FakeFocus:
    def __init__(self):
        self.enabled = False
        self.dim_level = 150

    def enable(self):
        self.enabled = True
        return True

    def disable(self):
        self.enabled = False
        return True

    def set_dim_level(self, level):
        self.dim_level = int(level)
        return True


class FakeScheduler(QObject):
    next_event_changed = Signal(object)
    running_changed = Signal(bool)
    manual_override_changed = Signal(bool)
    error = Signal(str, str)

    def __init__(self):
        super().__init__()
        self.running = True
        self.manual_override = False
        self.next_event = None
        self.next_event_at = None
        self.callback = None

    def set_profile_callback(self, callback):
        self.callback = callback

    def set_manual_override(self, enabled=True):
        self.manual_override = bool(enabled)
        self.manual_override_changed.emit(self.manual_override)


class TransactionalScheduler(QObject):
    next_event_changed = Signal(object)
    running_changed = Signal(bool)
    manual_override_changed = Signal(bool)
    error = Signal(str, str)

    def __init__(self):
        super().__init__()
        self.running = False
        self.manual_override = True
        self.current_profile = "office"
        self.next_event = "baseline"
        self.next_event_at = "baseline-at"
        self.next_profile = "office"
        self.callback = None
        self.start_profile = "night"
        self.reschedule_profile = "reading"

    def set_profile_callback(self, callback):
        self.callback = callback

    def set_manual_override(self, enabled=True):
        self.manual_override = bool(enabled)
        self.manual_override_changed.emit(self.manual_override)

    def snapshot_runtime(self):
        return {
            "running": self.running,
            "manual_override": self.manual_override,
            "current_profile": self.current_profile,
            "next_event": self.next_event,
            "next_event_at": self.next_event_at,
            "next_profile": self.next_profile,
        }

    def restore_runtime(self, snapshot):
        for name, value in snapshot.items():
            setattr(self, name, value)

    def start(self, *, defer_apply=False):
        self.running = True
        self.manual_override = False
        self.current_profile = self.start_profile
        self.next_event = "after-start"
        self.next_event_at = "start-at"
        self.next_profile = "office"
        if not defer_apply and self.callback is not None:
            self.callback(self.current_profile)

    def stop(self):
        self.running = False
        self.manual_override = False
        self.current_profile = None
        self.next_event = None
        self.next_event_at = None
        self.next_profile = None

    def reschedule(self, *, defer_apply=False):
        self.manual_override = False
        self.current_profile = self.reschedule_profile
        self.next_event = "after-location"
        self.next_event_at = "location-at"
        self.next_profile = "night"
        if not defer_apply and self.callback is not None:
            self.callback(self.current_profile)


class ManualContextSensor(QObject):
    snapshot_changed = Signal(object)
    availability_changed = Signal(bool, str)

    def __init__(self):
        super().__init__()
        self.current_snapshot = ContextSnapshot(notification_mode="normal")

    def publish(self, snapshot):
        self.current_snapshot = snapshot
        self.snapshot_changed.emit(snapshot)

    def start(self):
        pass

    def stop(self):
        pass


def _controller():
    store = CountingStore()
    settings = Settings(store)
    gamma = ManualGamma()
    dimmer = FakeDimmer()
    reminder = BreakReminder()
    focus = FakeFocus()
    controller = AppController(
        settings,
        blue_filter=gamma,
        dimmer=dimmer,
        break_reminder=reminder,
        focus_mode=focus,
    )
    return controller, settings, store, gamma, dimmer, reminder, focus


def _schedule_controller():
    store = CountingStore()
    settings = Settings(store)
    gamma = ManualGamma()
    dimmer = FakeDimmer()
    reminder = BreakReminder()
    scheduler = TransactionalScheduler()
    controller = AppController(
        settings,
        blue_filter=gamma,
        dimmer=dimmer,
        break_reminder=reminder,
        scheduler=scheduler,
    )
    return controller, settings, store, gamma, dimmer, scheduler


def test_only_latest_revision_commits_after_out_of_order_completion(qtbot):
    controller, settings, store, gamma, _dimmer, _reminder, _focus = _controller()
    baseline_syncs = store.sync_count
    failures = QSignalSpy(controller.operation_failed)

    assert controller.set_filter_enabled(True) is True
    enable = gamma.requests[-1]
    assert settings.filter_enabled is False
    assert controller.state.display.filter_enabled is True

    assert controller.set_filter_enabled(False) is True
    disable = gamma.requests[-1]
    gamma.complete(disable, success=True)
    qtbot.waitUntil(lambda: store.sync_count == baseline_syncs + 1)

    gamma.complete(
        enable,
        success=False,
        code="gamma_apply_failed",
        message="late failure",
    )
    qtbot.wait(10)

    assert settings.filter_enabled is False
    assert controller.state.display.filter_enabled is False
    assert store.sync_count == baseline_syncs + 1
    assert failures.count() == 0


def test_preview_does_not_persist_and_commit_has_own_barrier(qtbot):
    controller, settings, store, gamma, _dimmer, _reminder, _focus = _controller()
    settings.filter_enabled = True
    gamma.enabled = True
    baseline_syncs = store.sync_count

    assert controller.set_color_temperature(4300, persist=False) is True
    preview = gamma.requests[-1]
    assert preview.purpose == "preview"
    assert settings.color_temperature == 6500
    assert store.sync_count == baseline_syncs

    assert controller.set_color_temperature(4300, persist=True) is True
    commit = gamma.requests[-1]
    assert commit.request_id != preview.request_id
    assert commit.purpose == "commit"
    assert settings.color_temperature == 6500

    gamma.complete(preview, success=True)
    gamma.complete(commit, success=True)
    qtbot.waitUntil(lambda: settings.color_temperature == 4300)

    assert store.sync_count == baseline_syncs + 1
    assert settings.current_preset == "custom"


def test_profile_failure_compensates_dimmer_and_keeps_preferences(qtbot):
    controller, settings, _store, gamma, dimmer, _reminder, _focus = _controller()
    failures = QSignalSpy(controller.operation_failed)

    assert controller.apply_display_profile("reading") is True
    apply_request = gamma.requests[-1]
    assert dimmer.enabled is True
    assert settings.current_preset == "custom"

    gamma.complete(
        apply_request,
        success=False,
        code="gamma_apply_failed",
        message="display rejected gamma",
    )
    qtbot.waitUntil(lambda: failures.count() >= 1)

    assert failures.at(0)[0] == "display_profile"
    assert settings.filter_enabled is False
    assert settings.dimmer_enabled is False
    assert settings.current_preset == "custom"
    assert dimmer.enabled is False
    compensation = gamma.requests[-1]
    assert compensation.purpose == "compensation"


def test_hdr_discovery_commits_preference_as_suppressed(qtbot):
    controller, settings, _store, gamma, _dimmer, _reminder, _focus = _controller()
    failures = QSignalSpy(controller.operation_failed)

    assert controller.set_filter_enabled(True) is True
    request = gamma.requests[-1]
    gamma.complete(
        request,
        success=False,
        code="hdr_active",
        message="HDR active",
        hdr_active=True,
    )
    qtbot.waitUntil(lambda: settings.filter_enabled is True)

    assert controller.state.display.filter_enabled is True
    assert controller.state.display_health.hdr_active is True
    assert "hdr_active" in controller.state.effective_policy.filter.suppressed_by
    assert failures.count() == 0


def test_hdr_off_reapplies_latest_enabled_preference(qtbot):
    controller, settings, _store, gamma, _dimmer, _reminder, _focus = _controller()
    settings.filter_enabled = True
    gamma.hdr_active = True
    controller._last_display_hdr_active = True

    gamma.hdr_active = False
    gamma.state_changed.emit()
    qtbot.waitUntil(
        lambda: bool(gamma.requests)
        and gamma.requests[-1].purpose == "hdr_restore"
    )
    restore = gamma.requests[-1]
    assert restore.kind == "enable"
    gamma.complete(restore, success=True)
    qtbot.waitUntil(lambda: gamma.enabled)

    assert settings.filter_enabled is True


def test_hdr_off_during_commit_reconciles_after_barrier(qtbot):
    controller, settings, _store, gamma, _dimmer, _reminder, _focus = _controller()
    gamma.hdr_active = True
    controller._last_display_hdr_active = True
    refresh = gamma.request_refresh()

    assert controller.set_filter_enabled(True) is True
    suppressed_commit = gamma.requests[-1]
    assert suppressed_commit.kind == "disable"

    gamma.complete(refresh, success=True, hdr_active=False)
    qtbot.wait(10)
    gamma.complete(suppressed_commit, success=True)
    qtbot.waitUntil(
        lambda: bool(gamma.requests)
        and gamma.requests[-1].purpose == "system"
        and gamma.requests[-1].kind == "enable"
    )
    restore = gamma.requests[-1]
    gamma.complete(restore, success=True)
    qtbot.waitUntil(lambda: gamma.enabled)

    assert settings.filter_enabled is True


def test_pending_display_commit_keeps_new_break_preference_on_success(qtbot):
    controller, settings, _store, gamma, _dimmer, reminder, _focus = _controller()

    assert controller.set_filter_enabled(True) is True
    request = gamma.requests[-1]
    assert controller.set_break_enabled(True) is True
    assert settings.break_enabled is True
    assert reminder.enabled is True

    gamma.complete(request, success=True)
    qtbot.waitUntil(lambda: settings.filter_enabled is True)

    assert settings.break_enabled is True
    assert reminder.enabled is True
    assert controller.state.effective_policy.breaks.desired_enabled is True
    assert controller.state.effective_policy.breaks.effective_enabled is True
    reminder.stop()


def test_pending_display_failure_does_not_rollback_new_break_preference(qtbot):
    controller, settings, _store, gamma, _dimmer, reminder, _focus = _controller()
    failures = QSignalSpy(controller.operation_failed)

    assert controller.set_filter_enabled(True) is True
    request = gamma.requests[-1]
    assert controller.set_break_enabled(True) is True

    gamma.complete(
        request,
        success=False,
        code="gamma_apply_failed",
        message="display rejected gamma",
    )
    qtbot.waitUntil(lambda: failures.count() >= 1)

    assert settings.filter_enabled is False
    assert settings.break_enabled is True
    assert reminder.enabled is True
    assert controller.state.effective_policy.breaks.desired_enabled is True
    assert controller.state.effective_policy.breaks.effective_enabled is True
    reminder.stop()


def test_pending_display_failure_does_not_rollback_new_focus_preference(qtbot):
    controller, settings, _store, gamma, _dimmer, _reminder, focus = _controller()
    failures = QSignalSpy(controller.operation_failed)

    assert controller.set_filter_enabled(True) is True
    request = gamma.requests[-1]
    assert controller.set_focus_enabled(True) is True

    gamma.complete(
        request,
        success=False,
        code="gamma_apply_failed",
        message="display rejected gamma",
    )
    qtbot.waitUntil(lambda: failures.count() >= 1)

    assert settings.filter_enabled is False
    assert settings.focus_enabled is True
    assert focus.enabled is True
    assert controller.state.effective_policy.focus.desired_enabled is True
    assert controller.state.effective_policy.focus.effective_enabled is True


def test_new_focus_command_supersedes_pending_restore_focus_intent(qtbot):
    controller, settings, _store, gamma, _dimmer, _reminder, focus = _controller()

    assert controller.restore_display_effects() is True
    restore = gamma.requests[-1]
    assert controller.set_focus_enabled(True) is True
    assert focus.enabled is True

    gamma.complete(restore, success=True)
    qtbot.waitUntil(lambda: not controller.state.display_health.pending)

    assert settings.focus_enabled is True
    assert focus.enabled is True
    assert controller.state.effective_policy.focus.desired_enabled is True
    assert controller.state.effective_policy.focus.effective_enabled is True


def test_runtime_change_extends_current_display_commit_barrier(qtbot):
    controller, settings, _store, gamma, _dimmer, _reminder, _focus = _controller()
    failures = QSignalSpy(controller.operation_failed)

    assert controller.set_filter_enabled(True) is True
    enable = gamma.requests[-1]
    assert controller.pause_all() is True
    disable = gamma.requests[-1]
    assert disable.kind == "disable"
    assert disable.revision > enable.revision
    assert disable.purpose == "commit"

    gamma.complete(enable, success=True)
    qtbot.wait(10)
    assert settings.filter_enabled is False

    gamma.complete(
        disable,
        success=False,
        code="gamma_apply_failed",
        message="pause transition failed",
    )
    qtbot.waitUntil(lambda: failures.count() >= 1)

    assert failures.at(0)[0] == "global_pause"
    assert settings.filter_enabled is False
    assert settings.global_pause_mode == "none"


def _enable_all_effects(settings, store, gamma, dimmer, reminder, focus):
    settings.filter_enabled = True
    settings.dimmer_enabled = True
    settings.dim_level = 80
    settings.break_enabled = True
    settings.focus_enabled = True
    settings.sync_checked()
    gamma.enabled = True
    gamma.current_temperature = settings.color_temperature
    dimmer.enable(settings.dim_level)
    reminder.start()
    focus.enable()
    return store.sync_count


def test_pause_waits_for_gamma_before_single_settings_commit(qtbot):
    controller, settings, store, gamma, dimmer, reminder, focus = _controller()
    baseline_syncs = _enable_all_effects(
        settings,
        store,
        gamma,
        dimmer,
        reminder,
        focus,
    )

    assert controller.pause_all(minutes=30) is True
    disable = gamma.requests[-1]
    assert settings.global_pause_mode == "none"
    assert controller.state.global_pause.active is True
    assert store.sync_count == baseline_syncs
    assert controller._pause_timer.isActive() is False

    gamma.complete(disable, success=True)
    qtbot.waitUntil(lambda: settings.global_pause_mode == "timed")

    assert store.sync_count == baseline_syncs + 1
    assert controller._pause_timer.isActive() is True
    assert gamma.enabled is False
    assert dimmer.enabled is False
    assert reminder.enabled is False
    assert focus.enabled is False


def test_pause_gamma_failure_rolls_back_pause_and_all_sync_effects(qtbot):
    controller, settings, store, gamma, dimmer, reminder, focus = _controller()
    baseline_syncs = _enable_all_effects(
        settings,
        store,
        gamma,
        dimmer,
        reminder,
        focus,
    )
    failures = QSignalSpy(controller.operation_failed)

    assert controller.pause_all() is True
    disable = gamma.requests[-1]
    gamma.complete(
        disable,
        success=False,
        code="gamma_apply_failed",
        message="pause gamma failed",
    )
    qtbot.waitUntil(lambda: failures.count() >= 1)

    assert failures.at(0)[0] == "global_pause"
    assert settings.global_pause_mode == "none"
    assert store.sync_count == baseline_syncs
    assert dimmer.enabled is True
    assert reminder.enabled is True
    assert focus.enabled is True
    compensation = gamma.requests[-1]
    assert compensation.purpose == "compensation"
    gamma.complete(compensation, success=True)
    qtbot.waitUntil(lambda: gamma.enabled)


def test_pause_sync_failure_restores_preferences_and_actual_effects(qtbot):
    controller, settings, store, gamma, dimmer, reminder, focus = _controller()
    _enable_all_effects(
        settings,
        store,
        gamma,
        dimmer,
        reminder,
        focus,
    )
    failures = QSignalSpy(controller.operation_failed)

    assert controller.pause_all() is True
    disable = gamma.requests[-1]
    store.fail_sync_count = 1
    gamma.complete(disable, success=True)
    qtbot.waitUntil(lambda: failures.count() >= 1)

    assert failures.at(0)[0] == "global_pause"
    assert settings.global_pause_mode == "none"
    assert dimmer.enabled is True
    assert reminder.enabled is True
    assert focus.enabled is True
    compensation = gamma.requests[-1]
    assert compensation.purpose == "compensation"
    gamma.complete(compensation, success=True)
    qtbot.waitUntil(lambda: gamma.enabled)


def test_resume_supersedes_pending_pause_and_old_failure_is_silent(qtbot):
    controller, settings, store, gamma, dimmer, reminder, focus = _controller()
    baseline_syncs = _enable_all_effects(
        settings,
        store,
        gamma,
        dimmer,
        reminder,
        focus,
    )
    failures = QSignalSpy(controller.operation_failed)

    assert controller.pause_all() is True
    disable = gamma.requests[-1]
    assert controller.resume_all() is True
    enable = gamma.requests[-1]
    assert enable.revision > disable.revision

    gamma.complete(
        disable,
        success=False,
        code="gamma_apply_failed",
        message="old pause failure",
    )
    gamma.complete(enable, success=True)
    qtbot.waitUntil(lambda: not controller.state.display_health.pending)

    assert failures.count() == 0
    assert settings.global_pause_mode == "none"
    assert store.sync_count == baseline_syncs + 1
    assert gamma.enabled is True
    assert dimmer.enabled is True
    assert reminder.enabled is True
    assert focus.enabled is True


def test_pause_failure_preserves_later_break_and_focus_preferences(qtbot):
    controller, settings, store, gamma, dimmer, reminder, focus = _controller()
    _enable_all_effects(
        settings,
        store,
        gamma,
        dimmer,
        reminder,
        focus,
    )
    failures = QSignalSpy(controller.operation_failed)

    assert controller.pause_all() is True
    disable = gamma.requests[-1]
    assert controller.set_break_enabled(False) is True
    assert controller.set_focus_enabled(False) is True
    gamma.complete(
        disable,
        success=False,
        code="gamma_apply_failed",
        message="pause gamma failed",
    )
    qtbot.waitUntil(lambda: failures.count() >= 1)

    assert settings.global_pause_mode == "none"
    assert settings.break_enabled is False
    assert settings.focus_enabled is False
    assert dimmer.enabled is True
    assert reminder.enabled is False
    assert focus.enabled is False


def test_pause_without_filter_target_commits_without_gamma_barrier():
    controller, settings, store, gamma, _dimmer, _reminder, _focus = _controller()
    baseline_syncs = store.sync_count

    assert controller.pause_all() is True

    assert gamma.requests == ()
    assert settings.global_pause_mode == "manual"
    assert store.sync_count == baseline_syncs + 1


def test_hdr_pause_and_resume_commit_without_gamma_until_hdr_off(qtbot):
    controller, settings, _store, gamma, _dimmer, _reminder, _focus = _controller()
    settings.filter_enabled = True
    gamma.hdr_active = True
    controller._last_display_hdr_active = True

    assert controller.pause_all() is True
    assert gamma.requests == ()
    assert settings.global_pause_mode == "manual"
    assert controller.resume_all() is True
    assert gamma.requests == ()
    assert settings.global_pause_mode == "none"

    gamma.hdr_active = False
    gamma.state_changed.emit()
    qtbot.waitUntil(
        lambda: bool(gamma.requests)
        and gamma.requests[-1].purpose == "hdr_restore"
    )
    restore = gamma.requests[-1]
    gamma.complete(restore, success=True)
    qtbot.waitUntil(lambda: gamma.enabled)


def test_timed_pause_expiring_before_gamma_settles_never_starts_timer(
    qtbot,
    monkeypatch,
):
    controller, settings, store, gamma, dimmer, reminder, focus = _controller()
    baseline_syncs = _enable_all_effects(
        settings,
        store,
        gamma,
        dimmer,
        reminder,
        focus,
    )
    now = [1_800_000_000.0]
    monkeypatch.setattr("opencareyes.controller.time.time", lambda: now[0])

    assert controller.pause_all(minutes=1) is True
    disable = gamma.requests[-1]
    now[0] += 61.0
    gamma.complete(disable, success=True)
    qtbot.waitUntil(
        lambda: bool(gamma.requests)
        and gamma.requests[-1].kind == "enable"
    )
    enable = gamma.requests[-1]
    gamma.complete(enable, success=True)
    qtbot.waitUntil(lambda: not controller.state.display_health.pending)

    assert settings.global_pause_mode == "none"
    assert controller._pause_timer.isActive() is False
    assert store.sync_count == baseline_syncs + 1
    assert gamma.enabled is True


def test_sync_failure_restores_only_display_and_compensates_actual_effects(qtbot):
    controller, settings, store, gamma, dimmer, reminder, _focus = _controller()
    failures = QSignalSpy(controller.operation_failed)

    assert controller.apply_display_profile("reading") is True
    apply_request = gamma.requests[-1]
    assert controller.set_break_enabled(True) is True
    store.fail_sync_count = 1

    gamma.complete(apply_request, success=True)
    qtbot.waitUntil(lambda: failures.count() >= 1)

    assert failures.at(0)[0] == "display_profile"
    assert settings.filter_enabled is False
    assert settings.dimmer_enabled is False
    assert settings.break_enabled is True
    assert reminder.enabled is True
    assert dimmer.enabled is False
    compensation = gamma.requests[-1]
    assert compensation.purpose == "compensation"
    gamma.complete(compensation, success=True)
    qtbot.waitUntil(lambda: gamma.enabled is False)
    reminder.stop()


def test_compensation_failure_is_visible(qtbot):
    controller, _settings, _store, gamma, _dimmer, _reminder, _focus = (
        _controller()
    )
    failures = QSignalSpy(controller.operation_failed)

    assert controller.apply_display_profile("reading") is True
    apply_request = gamma.requests[-1]
    gamma.complete(
        apply_request,
        success=False,
        code="gamma_apply_failed",
        message="apply failed",
    )
    qtbot.waitUntil(lambda: failures.count() >= 1)
    compensation = gamma.requests[-1]
    gamma.complete(
        compensation,
        success=False,
        code="gamma_rollback_failed",
        message="compensation failed",
    )
    qtbot.waitUntil(lambda: failures.count() >= 2)

    assert [failures.at(index)[0] for index in range(failures.count())] == [
        "display_profile",
        "display_profile_rollback",
    ]


def test_manual_override_is_claimed_while_pending_and_restored_on_failure(
    qtbot,
):
    store = CountingStore()
    settings = Settings(store)
    gamma = ManualGamma()
    scheduler = FakeScheduler()
    controller = AppController(
        settings,
        blue_filter=gamma,
        scheduler=scheduler,
    )
    failures = QSignalSpy(controller.operation_failed)

    assert controller.set_filter_enabled(True) is True
    request = gamma.requests[-1]
    assert scheduler.manual_override is True

    gamma.complete(
        request,
        success=False,
        code="gamma_apply_failed",
        message="apply failed",
    )
    qtbot.waitUntil(lambda: failures.count() >= 1)

    assert scheduler.manual_override is False


def test_schedule_enable_sync_failure_after_effect_restores_everything(qtbot):
    controller, settings, store, gamma, _dimmer, scheduler = (
        _schedule_controller()
    )
    baseline = scheduler.snapshot_runtime()
    assert controller.set_schedule(
        True,
        mode="fixed",
        on_time="19:00",
        off_time="07:30",
        days=(0, 1, 2, 3, 4),
    ) is True
    request = gamma.requests[-1]
    store.fail_sync_count = 1
    gamma.complete(request, success=True)
    qtbot.waitUntil(lambda: bool(gamma.requests))

    assert settings.filter_schedule_enabled is False
    assert scheduler.snapshot_runtime() == baseline
    compensation = gamma.requests[-1]
    assert compensation.kind == "disable"
    assert compensation.purpose == "compensation"
    gamma.complete(compensation, success=True)


def test_schedule_disable_sync_failure_restores_running_scheduler():
    controller, settings, store, gamma, _dimmer, scheduler = (
        _schedule_controller()
    )
    settings.filter_schedule_enabled = True
    scheduler.running = True
    scheduler.manual_override = True
    scheduler.current_profile = "night"
    scheduler.next_event = "off"
    scheduler.next_event_at = "tomorrow"
    scheduler.next_profile = "office"
    baseline = scheduler.snapshot_runtime()
    store.fail_sync_count = 1

    assert controller.set_schedule(False) is False

    assert settings.filter_schedule_enabled is True
    assert scheduler.snapshot_runtime() == baseline
    assert gamma.requests == ()


def test_location_sync_failure_after_effect_restores_reschedule_state(qtbot):
    controller, settings, store, gamma, _dimmer, scheduler = (
        _schedule_controller()
    )
    settings.latitude = 31.23
    settings.longitude = 121.47
    settings.city = "上海"
    settings.location_configured = True
    scheduler.running = True
    scheduler.manual_override = True
    baseline = scheduler.snapshot_runtime()
    assert controller.set_location(39.90, 116.40, "北京") is True
    request = gamma.requests[-1]
    store.fail_sync_count = 1
    gamma.complete(request, success=True)
    qtbot.waitUntil(lambda: bool(gamma.requests))

    assert settings.latitude == 31.23
    assert settings.longitude == 121.47
    assert settings.city == "上海"
    assert scheduler.snapshot_runtime() == baseline
    compensation = gamma.requests[-1]
    assert compensation.purpose == "compensation"
    gamma.complete(compensation, success=True)


def test_schedule_and_location_success_each_sync_exactly_once(qtbot):
    controller, settings, store, gamma, _dimmer, scheduler = (
        _schedule_controller()
    )
    baseline_syncs = store.sync_count

    assert controller.set_schedule(
        True,
        mode="fixed",
        on_time="19:00",
        off_time="07:30",
        days=(0, 1, 2, 3, 4),
    ) is True
    assert store.sync_count == baseline_syncs
    gamma.complete(gamma.requests[-1], success=True)
    qtbot.waitUntil(lambda: store.sync_count == baseline_syncs + 1)
    assert settings.filter_schedule_enabled is True
    assert store.sync_count == baseline_syncs + 1

    location_syncs = store.sync_count
    scheduler.reschedule_profile = "reading"
    assert controller.set_location(39.90, 116.40, "北京") is True
    assert store.sync_count == location_syncs
    gamma.complete(gamma.requests[-1], success=True)
    qtbot.waitUntil(lambda: store.sync_count == location_syncs + 1)
    assert settings.city == "北京"
    assert store.sync_count == location_syncs + 1


def test_pending_schedule_is_not_auto_persisted_by_real_qsettings(
    qtbot,
    tmp_path,
):
    path = tmp_path / "opencareeyes.ini"
    settings = Settings(QSettings(str(path), QSettings.IniFormat))
    settings.filter_schedule_enabled = False
    settings.latitude = 31.23
    settings.longitude = 121.47
    settings.city = "上海"
    settings.location_configured = True
    settings.sync()
    gamma = ManualGamma()
    scheduler = TransactionalScheduler()
    controller = AppController(
        settings,
        blue_filter=gamma,
        dimmer=FakeDimmer(),
        scheduler=scheduler,
    )

    assert controller.set_schedule(
        True,
        mode="sun",
        latitude=39.90,
        longitude=116.40,
        city="北京",
        days=(0, 1, 2, 3, 4),
    ) is True
    request = gamma.requests[-1]
    assert settings.filter_schedule_enabled is False
    assert settings.city == "上海"
    assert scheduler.running is False

    qtbot.wait(1500)
    pending_reader = Settings(QSettings(str(path), QSettings.IniFormat))
    assert pending_reader.filter_schedule_enabled is False
    assert pending_reader.latitude == 31.23
    assert pending_reader.longitude == 121.47
    assert pending_reader.city == "上海"

    gamma.complete(request, success=True)
    qtbot.waitUntil(lambda: settings.filter_schedule_enabled is True)
    committed_reader = Settings(QSettings(str(path), QSettings.IniFormat))
    assert committed_reader.filter_schedule_enabled is True
    assert committed_reader.latitude == 39.90
    assert committed_reader.longitude == 116.40
    assert committed_reader.city == "北京"


def test_pending_schedule_keeps_later_break_commit_on_gamma_failure(qtbot):
    controller, settings, store, gamma, _dimmer, scheduler = (
        _schedule_controller()
    )
    failures = QSignalSpy(controller.operation_failed)
    baseline = scheduler.snapshot_runtime()

    assert controller.set_schedule(True, mode="fixed") is True
    schedule_request = gamma.requests[-1]
    assert controller.set_break_enabled(True) is True
    assert store.synced_values[-1].get("filter/schedule_enabled", False) is False
    assert store.synced_values[-1]["break/enabled"] is True

    gamma.complete(
        schedule_request,
        success=False,
        code="gamma_apply_failed",
        message="scheduled display failed",
    )
    qtbot.waitUntil(lambda: failures.count() >= 1)

    assert settings.filter_schedule_enabled is False
    assert settings.break_enabled is True
    assert scheduler.snapshot_runtime() == baseline
    assert store.synced_values[-1].get("filter/schedule_enabled", False) is False
    assert store.synced_values[-1]["break/enabled"] is True
    compensation = gamma.requests[-1]
    assert compensation.purpose == "compensation"
    gamma.complete(compensation, success=True)
    controller._break_reminder.stop()


def test_pending_schedule_then_manual_profile_commits_latest_with_override(
    qtbot,
):
    controller, settings, store, gamma, _dimmer, scheduler = (
        _schedule_controller()
    )
    baseline_syncs = store.sync_count

    assert controller.set_schedule(True, mode="fixed") is True
    scheduled = gamma.requests[-1]
    assert controller.apply_display_profile("reading") is True
    manual = gamma.requests[-1]
    assert manual.revision > scheduled.revision
    assert scheduler.running is False

    gamma.complete(scheduled, success=True)
    qtbot.wait(10)
    assert settings.filter_schedule_enabled is False
    assert store.sync_count == baseline_syncs

    gamma.complete(manual, success=True)
    qtbot.waitUntil(lambda: settings.current_preset == "reading")

    assert settings.filter_schedule_enabled is True
    assert scheduler.running is True
    assert scheduler.manual_override is True
    assert settings.color_temperature == 4500
    assert store.sync_count == baseline_syncs + 1


def test_pending_schedule_then_pause_commits_both_intents(qtbot):
    controller, settings, store, gamma, _dimmer, scheduler = (
        _schedule_controller()
    )
    baseline_syncs = store.sync_count

    assert controller.set_schedule(True, mode="fixed") is True
    scheduled = gamma.requests[-1]
    assert controller.pause_all() is True
    paused = gamma.requests[-1]
    assert paused.kind == "disable"
    assert paused.revision > scheduled.revision

    gamma.complete(scheduled, success=True)
    qtbot.wait(10)
    assert settings.filter_schedule_enabled is False
    assert settings.global_pause_mode == "none"

    gamma.complete(paused, success=True)
    qtbot.waitUntil(lambda: settings.global_pause_mode == "manual")

    assert settings.filter_schedule_enabled is True
    assert scheduler.running is True
    assert settings.current_preset == "night"
    assert store.sync_count == baseline_syncs + 1


def test_replaced_pending_schedule_failure_restores_original_baseline(qtbot):
    controller, settings, _store, gamma, _dimmer, scheduler = (
        _schedule_controller()
    )
    settings.latitude = 31.23
    settings.longitude = 121.47
    settings.city = "上海"
    settings.location_configured = True
    baseline = scheduler.snapshot_runtime()
    failures = QSignalSpy(controller.operation_failed)

    assert controller.set_schedule(
        True,
        mode="fixed",
        on_time="18:30",
        off_time="08:00",
    ) is True
    first = gamma.requests[-1]
    assert controller.set_schedule(
        True,
        mode="sun",
        latitude=39.90,
        longitude=116.40,
        city="北京",
    ) is True
    replacement = gamma.requests[-1]
    assert replacement.revision > first.revision

    gamma.complete(first, success=True)
    gamma.complete(
        replacement,
        success=False,
        code="gamma_apply_failed",
        message="replacement failed",
    )
    qtbot.waitUntil(lambda: failures.count() >= 1)

    assert settings.filter_schedule_enabled is False
    assert settings.schedule_mode == "fixed"
    assert settings.schedule_on_time == "19:00"
    assert settings.schedule_off_time == "07:30"
    assert settings.latitude == 31.23
    assert settings.longitude == 121.47
    assert settings.city == "上海"
    assert scheduler.snapshot_runtime() == baseline
    compensation = gamma.requests[-1]
    assert compensation.purpose == "compensation"
    gamma.complete(compensation, success=True)


def test_schedule_profile_failure_restores_configuration_and_effects(qtbot):
    controller, settings, _store, gamma, dimmer, scheduler = (
        _schedule_controller()
    )
    failures = QSignalSpy(controller.operation_failed)
    baseline = scheduler.snapshot_runtime()
    settings.latitude = 31.23
    settings.longitude = 121.47
    settings.city = "上海"
    settings.location_configured = True

    assert controller.set_schedule(
        True,
        mode="sun",
        latitude=39.90,
        longitude=116.40,
        city="北京",
        days=(0, 1, 2, 3, 4),
    ) is True
    assert len(gamma.requests) == 1
    apply_request = gamma.requests[-1]
    assert settings.filter_schedule_enabled is False
    assert scheduler.snapshot_runtime() == baseline
    assert dimmer.enabled is True

    gamma.complete(
        apply_request,
        success=False,
        code="gamma_apply_failed",
        message="scheduled profile failed",
    )
    qtbot.waitUntil(lambda: failures.count() >= 1)

    assert failures.at(0)[0] == "schedule"
    assert settings.filter_schedule_enabled is False
    assert settings.current_preset == "custom"
    assert settings.latitude == 31.23
    assert settings.longitude == 121.47
    assert settings.city == "上海"
    assert scheduler.snapshot_runtime() == baseline
    assert dimmer.enabled is False
    compensation = gamma.requests[-1]
    assert compensation.purpose == "compensation"
    gamma.complete(compensation, success=True)


def test_location_profile_failure_restores_location_and_scheduler(qtbot):
    controller, settings, _store, gamma, _dimmer, scheduler = (
        _schedule_controller()
    )
    settings.latitude = 31.23
    settings.longitude = 121.47
    settings.city = "上海"
    settings.location_configured = True
    scheduler.running = True
    scheduler.manual_override = True
    baseline = scheduler.snapshot_runtime()
    failures = QSignalSpy(controller.operation_failed)

    assert controller.set_location(39.90, 116.40, "北京") is True
    request = gamma.requests[-1]
    gamma.complete(
        request,
        success=False,
        code="gamma_apply_failed",
        message="location profile failed",
    )
    qtbot.waitUntil(lambda: failures.count() >= 1)

    assert settings.latitude == 31.23
    assert settings.longitude == 121.47
    assert scheduler.snapshot_runtime() == baseline
    compensation = gamma.requests[-1]
    assert compensation.purpose == "compensation"
    gamma.complete(compensation, success=True)


def _context_controller():
    store = CountingStore()
    settings = Settings(store)
    settings.app_rules = (
        {
            "app_id": "game.exe",
            "breaks": False,
            "focus": False,
            "filter": True,
            "dimmer": False,
        },
    )
    gamma = ManualGamma()
    effects = EffectCoordinator(settings, blue_filter=gamma)
    sensor = ManualContextSensor()
    runtime = ContextCoordinator(settings, sensor, effects)
    controller = AppController(
        settings,
        blue_filter=gamma,
        effect_coordinator=effects,
    )
    controller.attach_context_runtime(runtime)
    return controller, settings, gamma, sensor


def test_context_reconcile_signal_extends_display_commit_barrier(qtbot):
    controller, settings, gamma, sensor = _context_controller()

    assert controller.set_filter_enabled(True) is True
    enable = gamma.requests[-1]
    sensor.publish(ContextSnapshot(foreground_app_id="game.exe"))
    qtbot.waitUntil(lambda: len(gamma.requests) >= 2, timeout=1000)
    suppress = gamma.requests[-1]
    assert suppress.kind == "disable"
    assert suppress.revision == enable.revision

    gamma.complete(enable, success=True)
    qtbot.wait(10)
    assert settings.filter_enabled is False

    gamma.complete(suppress, success=True)
    qtbot.waitUntil(lambda: settings.filter_enabled is True)
    assert controller.state.effective_policy.filter.suppressed_by == (
        "app_rule",
    )


def test_context_barrier_failure_is_not_silent(qtbot):
    controller, settings, gamma, sensor = _context_controller()
    failures = QSignalSpy(controller.operation_failed)

    assert controller.set_filter_enabled(True) is True
    enable = gamma.requests[-1]
    sensor.publish(ContextSnapshot(foreground_app_id="game.exe"))
    qtbot.waitUntil(lambda: len(gamma.requests) >= 2, timeout=1000)
    suppress = gamma.requests[-1]
    gamma.complete(enable, success=True)
    gamma.complete(
        suppress,
        success=False,
        code="gamma_apply_failed",
        message="context disable failed",
    )
    qtbot.waitUntil(lambda: failures.count() >= 1)

    assert failures.at(0)[0] == "filter_toggle"
    assert settings.filter_enabled is False


def test_old_context_request_failure_waits_for_newer_barrier(qtbot):
    controller, settings, gamma, sensor = _context_controller()
    failures = QSignalSpy(controller.operation_failed)

    assert controller.set_filter_enabled(True) is True
    enable = gamma.requests[-1]
    sensor.publish(ContextSnapshot(foreground_app_id="game.exe"))
    qtbot.waitUntil(lambda: len(gamma.requests) >= 2, timeout=1000)
    suppress = gamma.requests[-1]

    gamma.complete(
        enable,
        success=False,
        code="gamma_apply_failed",
        message="obsolete enable failed",
    )
    qtbot.wait(10)
    assert failures.count() == 0
    assert settings.filter_enabled is False

    gamma.complete(suppress, success=True)
    qtbot.waitUntil(lambda: settings.filter_enabled is True)

    assert failures.count() == 0
    assert controller.state.effective_policy.filter.suppressed_by == (
        "app_rule",
    )


def test_new_context_result_cannot_commit_until_older_request_finishes(qtbot):
    controller, settings, gamma, sensor = _context_controller()
    failures = QSignalSpy(controller.operation_failed)

    assert controller.set_filter_enabled(True) is True
    enable = gamma.requests[-1]
    sensor.publish(ContextSnapshot(foreground_app_id="game.exe"))
    qtbot.waitUntil(lambda: len(gamma.requests) >= 2, timeout=1000)
    suppress = gamma.requests[-1]

    gamma.complete(suppress, success=True)
    qtbot.wait(10)
    assert failures.count() == 0
    assert settings.filter_enabled is False

    gamma.complete(
        enable,
        success=False,
        code="gamma_apply_failed",
        message="obsolete enable failed",
    )
    qtbot.waitUntil(lambda: settings.filter_enabled is True)

    assert failures.count() == 0
    assert controller.state.effective_policy.filter.suppressed_by == (
        "app_rule",
    )
