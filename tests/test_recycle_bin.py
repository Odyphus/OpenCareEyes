"""Tests for the confirmation-preserving recycle-bin wrapper."""

import ctypes

from opencareyes.platform.recycle_bin import (
    SHERB_NOCONFIRMATION,
    RecycleBinService,
)


class FakeShell32:
    def __init__(self, *, empty_result=0):
        self.empty_result = empty_result
        self.empty_calls = []

    def SHQueryRecycleBinW(self, root_path, info_pointer):
        info_pointer._obj.i64NumItems = 4
        info_pointer._obj.i64Size = 12345
        return 0

    def SHEmptyRecycleBinW(self, parent_hwnd, root_path, flags):
        self.empty_calls.append((parent_hwnd, root_path, flags))
        return self.empty_result


def test_query_reports_count_and_size_without_emptying():
    shell = FakeShell32()
    service = RecycleBinService(shell32=shell)
    info = service.query()

    assert info.item_count == 4
    assert info.size_bytes == 12345
    assert shell.empty_calls == []


def test_empty_never_disables_windows_confirmation():
    shell = FakeShell32()
    result = RecycleBinService(shell32=shell).empty(parent_hwnd=123)

    assert result.status == "completed"
    assert shell.empty_calls[0][0] == 123
    assert shell.empty_calls[0][2] & SHERB_NOCONFIRMATION == 0


def test_windows_cancel_is_not_reported_as_success():
    cancelled_hresult = ctypes.c_long(0x800704C7).value
    result = RecycleBinService(shell32=FakeShell32(empty_result=cancelled_hresult)).empty()
    assert result.status == "cancelled"


class BrokenShell32:
    def SHQueryRecycleBinW(self, _root_path, _info_pointer):
        raise OSError("failure")

    def SHEmptyRecycleBinW(self, _parent_hwnd, _root_path, _flags):
        raise OSError("failure")


def test_native_failures_are_visible_but_do_not_raise():
    service = RecycleBinService(shell32=BrokenShell32())
    assert service.query().available is False
    assert service.empty().status == "failed"
