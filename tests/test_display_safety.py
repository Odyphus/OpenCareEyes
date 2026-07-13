"""Display safety and aggregate Gamma rollback tests."""

from __future__ import annotations

import ctypes

import pytest

from opencareyes.core import blue_light_filter as filter_module
from opencareyes.core.blue_light_filter import BlueLightFilter, _GammaArray
from opencareyes.core.display_capabilities import AdvancedColorStatus


class _Monitors:
    def __init__(self, names=("DISPLAY1", "DISPLAY2")):
        self.names = names
        self.refresh_count = 0

    def get_monitors(self):
        return [{"name": name} for name in self.names]

    def refresh(self):
        self.refresh_count += 1


def _identity_ramp() -> _GammaArray:
    ramp = _GammaArray()
    for channel in range(3):
        for index in range(256):
            ramp[channel * 256 + index] = index * 257
    return ramp


def _offset_ramp(offset: int) -> _GammaArray:
    ramp = _identity_ramp()
    for index in range(len(ramp)):
        ramp[index] = min(65535, int(ramp[index]) + int(offset))
    return ramp


def _identity(name: str) -> tuple[str, ...]:
    return (f"monitor-interface:{name.casefold()}",)


def _install_fake_gamma(
    monkeypatch,
    *,
    fail_device: int | None = None,
    fail_restore_device: int | None = None,
):
    names = {"DISPLAY1": 1, "DISPLAY2": 2}
    original = {handle: _identity_ramp() for handle in names.values()}
    current = {
        handle: _GammaArray.from_buffer_copy(bytes(ramp))
        for handle, ramp in original.items()
    }
    target_calls = []
    restore_failures = 1 if fail_restore_device is not None else 0

    monkeypatch.setattr(filter_module, "CreateDCW", lambda _kind, name, *_: names[name])
    monkeypatch.setattr(filter_module, "DeleteDC", lambda _dc: True)

    def get_ramp(dc, pointer):
        ctypes.memmove(pointer, bytes(current[int(dc)]), ctypes.sizeof(_GammaArray))
        return True

    def set_ramp(dc, pointer):
        nonlocal restore_failures
        handle = int(dc)
        incoming = _GammaArray.from_buffer_copy(
            ctypes.string_at(pointer, ctypes.sizeof(_GammaArray))
        )
        is_original = bytes(incoming) == bytes(original[handle])
        if (
            is_original
            and handle == fail_restore_device
            and restore_failures > 0
        ):
            restore_failures -= 1
            return False
        if not is_original:
            target_calls.append(handle)
            if handle == fail_device:
                return False
        current[handle] = incoming
        return True

    monkeypatch.setattr(filter_module, "GetDeviceGammaRamp", get_ramp)
    monkeypatch.setattr(filter_module, "SetDeviceGammaRamp", set_ramp)
    return original, current, target_calls


def test_hdr_active_blocks_gamma_without_touching_displays(monkeypatch):
    _original, _current, calls = _install_fake_gamma(monkeypatch)
    service = BlueLightFilter(
        _Monitors(),
        hdr_probe=lambda: AdvancedColorStatus(True, True, True, "hdr_active"),
        identity_resolver=_identity,
    )

    assert service.enable(4500) is False
    assert service.enabled is False
    assert service.last_error_code == "hdr_active"
    assert calls == []


def test_gamma_requires_every_display_and_rolls_back_partial_success(monkeypatch):
    original, current, calls = _install_fake_gamma(monkeypatch, fail_device=2)
    service = BlueLightFilter(
        _Monitors(),
        hdr_probe=lambda: AdvancedColorStatus(False, False, True, "sdr_ready"),
        identity_resolver=_identity,
    )

    assert service.enable(4200) is False
    assert calls == [1, 2]
    assert service.enabled is False
    assert service.last_error_code == "gamma_apply_failed"
    assert all(bytes(current[key]) == bytes(original[key]) for key in original)


def test_gamma_reports_enabled_only_after_verified_all_target_apply(monkeypatch):
    _original, _current, calls = _install_fake_gamma(monkeypatch)
    service = BlueLightFilter(
        _Monitors(),
        hdr_probe=lambda: AdvancedColorStatus(False, False, True, "sdr_ready"),
        identity_resolver=_identity,
    )

    assert service.enable(4800) is True
    assert calls == [1, 2]
    assert service.enabled is True
    assert service.current_temperature == 4800
    assert service.last_error_code == ""


@pytest.mark.parametrize(
    ("operation", "expected"),
    (
        ("enable", False),
        ("temperature", False),
        ("disable", True),
        ("refresh", True),
    ),
)
def test_each_gamma_entry_point_reprobes_and_never_writes_in_hdr(
    monkeypatch,
    operation,
    expected,
):
    _install_fake_gamma(monkeypatch)
    active = [False]
    probes = []

    def probe():
        probes.append(active[0])
        return AdvancedColorStatus(True, active[0], True, "test")

    underlying = filter_module.SetDeviceGammaRamp
    writes = []

    def tracked_set(dc, pointer):
        writes.append(int(dc))
        return underlying(dc, pointer)

    monkeypatch.setattr(filter_module, "SetDeviceGammaRamp", tracked_set)
    service = BlueLightFilter(
        _Monitors(),
        hdr_probe=probe,
        identity_resolver=_identity,
    )
    assert service.enable(4800) is True

    writes.clear()
    before_probe_count = len(probes)
    active[0] = True
    result = {
        "enable": lambda: service.enable(4300),
        "temperature": lambda: service.set_temperature(4300),
        "disable": service.disable,
        "refresh": service.refresh_screens,
    }[operation]()

    assert result is expected
    assert len(probes) == before_probe_count + 1
    assert writes == []
    assert service.enabled is False
    assert service.last_error_code == "hdr_active"
    assert service._original_ramps == {}


def test_hdr_transition_discards_old_baseline_and_recaptures_sdr_state(
    monkeypatch,
):
    _original, current, _calls = _install_fake_gamma(monkeypatch)
    active = [False]
    service = BlueLightFilter(
        _Monitors(("DISPLAY1",)),
        hdr_probe=lambda: AdvancedColorStatus(True, active[0], True, "test"),
        identity_resolver=_identity,
    )

    assert service.enable(4600) is True
    active[0] = True
    assert service.refresh_screens() is True
    assert service._original_ramps == {}

    sdr_baseline = _offset_ramp(7)
    current[1] = _GammaArray.from_buffer_copy(bytes(sdr_baseline))
    active[0] = False
    assert service.enable(4300) is True
    assert service.disable() is True
    assert bytes(current[1]) == bytes(sdr_baseline)


def test_enable_rechecks_hdr_after_capture_before_first_gamma_write(monkeypatch):
    _install_fake_gamma(monkeypatch)
    active = [False]
    probes = []
    writes = []
    underlying_get = filter_module.GetDeviceGammaRamp
    underlying_set = filter_module.SetDeviceGammaRamp

    def probe():
        probes.append(active[0])
        return AdvancedColorStatus(True, active[0], True, "test")

    def get_then_enable_hdr(dc, pointer):
        result = underlying_get(dc, pointer)
        active[0] = True
        return result

    def tracked_set(dc, pointer):
        writes.append(int(dc))
        return underlying_set(dc, pointer)

    monkeypatch.setattr(filter_module, "GetDeviceGammaRamp", get_then_enable_hdr)
    monkeypatch.setattr(filter_module, "SetDeviceGammaRamp", tracked_set)
    service = BlueLightFilter(
        _Monitors(),
        hdr_probe=probe,
        identity_resolver=_identity,
    )

    assert service.enable(4500) is False
    assert probes == [False, True]
    assert writes == []
    assert service.last_error_code == "hdr_active"


def test_temperature_final_prewrite_probe_blocks_gamma_and_preserves_hdr(
    monkeypatch,
):
    _install_fake_gamma(monkeypatch)
    probes = []
    writes = []
    underlying_set = filter_module.SetDeviceGammaRamp

    def probe():
        active = len(probes) >= 3
        probes.append(active)
        return AdvancedColorStatus(True, active, True, "test")

    def tracked_set(dc, pointer):
        writes.append(int(dc))
        return underlying_set(dc, pointer)

    monkeypatch.setattr(filter_module, "SetDeviceGammaRamp", tracked_set)
    service = BlueLightFilter(
        _Monitors(),
        hdr_probe=probe,
        identity_resolver=_identity,
    )
    assert service.enable(4800) is True

    writes.clear()
    assert service.set_temperature(4300) is False
    assert probes == [False, False, False, True]
    assert writes == []
    assert service.enabled is False
    assert service.last_error_code == "hdr_active"


def test_disable_final_prerestore_probe_is_safe_hdr_suppression(monkeypatch):
    _install_fake_gamma(monkeypatch)
    probes = []
    writes = []
    underlying_set = filter_module.SetDeviceGammaRamp

    def probe():
        active = len(probes) >= 3
        probes.append(active)
        return AdvancedColorStatus(True, active, True, "test")

    def tracked_set(dc, pointer):
        writes.append(int(dc))
        return underlying_set(dc, pointer)

    monkeypatch.setattr(filter_module, "SetDeviceGammaRamp", tracked_set)
    service = BlueLightFilter(
        _Monitors(),
        hdr_probe=probe,
        identity_resolver=_identity,
    )
    assert service.enable(4800) is True

    writes.clear()
    assert service.disable() is True
    assert probes == [False, False, False, True]
    assert writes == []
    assert service.enabled is False
    assert service.last_error_code == "hdr_active"


def test_refresh_rechecks_hdr_after_replacement_capture(monkeypatch):
    _original, current, _calls = _install_fake_gamma(monkeypatch)
    active = [False]
    targets = [("monitor-a",)]
    service = BlueLightFilter(
        _Monitors(("DISPLAY1",)),
        hdr_probe=lambda: AdvancedColorStatus(True, active[0], True, "test"),
        identity_resolver=lambda _name: targets[0],
    )
    assert service.enable(4500) is True

    current[1] = _offset_ramp(13)
    targets[0] = ("monitor-b",)
    writes = []
    underlying_get = filter_module.GetDeviceGammaRamp
    underlying_set = filter_module.SetDeviceGammaRamp

    def get_then_enable_hdr(dc, pointer):
        result = underlying_get(dc, pointer)
        active[0] = True
        return result

    def tracked_set(dc, pointer):
        writes.append(int(dc))
        return underlying_set(dc, pointer)

    monkeypatch.setattr(filter_module, "GetDeviceGammaRamp", get_then_enable_hdr)
    monkeypatch.setattr(filter_module, "SetDeviceGammaRamp", tracked_set)

    assert service.refresh_screens() is True
    assert writes == []
    assert service.enabled is False
    assert service.last_error_code == "hdr_active"
    assert service._original_ramps == {}


def test_failed_partial_rollback_keeps_baseline_until_disable_retry(
    monkeypatch,
):
    original, current, calls = _install_fake_gamma(
        monkeypatch,
        fail_device=2,
        fail_restore_device=1,
    )
    service = BlueLightFilter(
        _Monitors(),
        hdr_probe=lambda: AdvancedColorStatus(False, False, True, "sdr_ready"),
        identity_resolver=_identity,
    )

    assert service.enable(4200) is False
    assert calls == [1, 2]
    assert service.enabled is False
    assert service.last_error_code == "gamma_rollback_failed"
    assert service._original_ramps
    assert bytes(current[1]) != bytes(original[1])

    assert service.disable() is True
    assert service.last_error_code == ""
    assert service._original_ramps == {}
    assert all(bytes(current[key]) == bytes(original[key]) for key in original)


def test_clone_target_change_reuses_unfiltered_source_baseline(monkeypatch):
    original, current, _calls = _install_fake_gamma(monkeypatch)
    targets = [("monitor-a",)]
    service = BlueLightFilter(
        _Monitors(("DISPLAY1",)),
        hdr_probe=lambda: AdvancedColorStatus(False, False, True, "sdr_ready"),
        identity_resolver=lambda _name: targets[0],
    )

    assert service.enable(4200) is True
    targets[0] = ("monitor-a", "monitor-b")
    assert service.refresh_screens() is True
    assert service.disable() is True
    assert bytes(current[1]) == bytes(original[1])


def test_replaced_target_captures_and_restores_new_source_baseline(monkeypatch):
    _original, current, _calls = _install_fake_gamma(monkeypatch)
    targets = [("monitor-a",)]
    service = BlueLightFilter(
        _Monitors(("DISPLAY1",)),
        hdr_probe=lambda: AdvancedColorStatus(False, False, True, "sdr_ready"),
        identity_resolver=lambda _name: targets[0],
    )

    assert service.enable(4200) is True
    replacement_baseline = _offset_ramp(11)
    current[1] = _GammaArray.from_buffer_copy(bytes(replacement_baseline))
    targets[0] = ("monitor-b",)
    assert service.refresh_screens() is True
    assert service.disable() is True
    assert bytes(current[1]) == bytes(replacement_baseline)


def test_distinct_target_interfaces_do_not_share_baselines(monkeypatch):
    _original, _current, _calls = _install_fake_gamma(monkeypatch)
    identities = {
        "DISPLAY1": ("same-model-instance-a",),
        "DISPLAY2": ("same-model-instance-b",),
    }
    service = BlueLightFilter(
        _Monitors(),
        hdr_probe=lambda: AdvancedColorStatus(False, False, True, "sdr_ready"),
        identity_resolver=lambda name: identities[name],
    )

    assert service.enable(4500) is True
    assert len(service._original_ramps) == 2
    assert {key[1] for key in service._original_ramps} == {
        ("same-model-instance-a",),
        ("same-model-instance-b",),
    }


@pytest.mark.parametrize("names", ((), ("DISPLAY1",)))
def test_untrusted_or_missing_display_identity_fails_without_gamma_io(
    monkeypatch,
    names,
):
    _install_fake_gamma(monkeypatch)
    reads = []
    writes = []
    underlying_get = filter_module.GetDeviceGammaRamp
    underlying_set = filter_module.SetDeviceGammaRamp

    def tracked_get(dc, pointer):
        reads.append(int(dc))
        return underlying_get(dc, pointer)

    def tracked_set(dc, pointer):
        writes.append(int(dc))
        return underlying_set(dc, pointer)

    monkeypatch.setattr(filter_module, "GetDeviceGammaRamp", tracked_get)
    monkeypatch.setattr(filter_module, "SetDeviceGammaRamp", tracked_set)
    service = BlueLightFilter(
        _Monitors(names),
        hdr_probe=lambda: AdvancedColorStatus(False, False, True, "sdr_ready"),
        identity_resolver=lambda _name: (),
    )

    assert service.enable(4500) is False
    assert reads == []
    assert writes == []
    assert service.last_error_code == "display_identity_unavailable"
    assert "可靠识别" in service.last_error_message
