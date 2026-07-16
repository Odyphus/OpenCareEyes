'''Small, confirmation-preserving wrapper around the Windows recycle bin.'''

from __future__ import annotations

import ctypes
import os
from dataclasses import dataclass


SHERB_NOCONFIRMATION = 0x00000001
SHERB_NOPROGRESSUI = 0x00000002
SHERB_NOSOUND = 0x00000004
_EMPTY_FLAGS = SHERB_NOPROGRESSUI | SHERB_NOSOUND
_ERROR_CANCELLED = 0x800704C7
_E_ABORT = 0x80004004


class _SHQUERYRBINFO(ctypes.Structure):
    _fields_ = [
        ('cbSize', ctypes.c_uint32),
        ('i64Size', ctypes.c_longlong),
        ('i64NumItems', ctypes.c_longlong),
    ]


@dataclass(frozen=True, slots=True)
class RecycleBinInfo:
    item_count: int = 0
    size_bytes: int = 0
    available: bool = True
    message: str = ''


@dataclass(frozen=True, slots=True)
class RecycleBinResult:
    status: str
    message: str = ''


class RecycleBinService:
    '''Query and empty the recycle bin while retaining Windows confirmation.'''

    def __init__(self, shell32: object | None = None) -> None:
        if shell32 is None and os.name == 'nt':
            shell32 = ctypes.WinDLL('shell32', use_last_error=True)
        self._shell32 = shell32
        self._configure_native_signatures()

    def _configure_native_signatures(self) -> None:
        if self._shell32 is None:
            return
        try:
            query = self._shell32.SHQueryRecycleBinW
            query.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(_SHQUERYRBINFO)]
            query.restype = ctypes.c_long
            empty = self._shell32.SHEmptyRecycleBinW
            empty.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint32]
            empty.restype = ctypes.c_long
        except (AttributeError, TypeError):
            # Lightweight test doubles expose normal bound methods rather than
            # ctypes function pointers and do not need native signatures.
            return

    @property
    def available(self) -> bool:
        return self._shell32 is not None

    def query(self, root_path: str | None = None) -> RecycleBinInfo:
        if self._shell32 is None:
            return RecycleBinInfo(available=False, message='此系统不支持回收站操作。')
        info = _SHQUERYRBINFO()
        info.cbSize = ctypes.sizeof(_SHQUERYRBINFO)
        try:
            result = self._shell32.SHQueryRecycleBinW(root_path, ctypes.byref(info))
        except Exception:
            return RecycleBinInfo(available=False, message='无法读取回收站状态。')
        if _hresult(result) != 0:
            return RecycleBinInfo(available=False, message='无法读取回收站状态。')
        return RecycleBinInfo(
            item_count=max(0, int(info.i64NumItems)),
            size_bytes=max(0, int(info.i64Size)),
        )

    def empty(self, *, parent_hwnd: int = 0, root_path: str | None = None) -> RecycleBinResult:
        if self._shell32 is None:
            return RecycleBinResult('unavailable', '此系统不支持回收站操作。')
        # Deliberately omit SHERB_NOCONFIRMATION. Windows must retain its own
        # confirmation even when the caller already displayed an item summary.
        flags = _EMPTY_FLAGS & ~SHERB_NOCONFIRMATION
        try:
            result = self._shell32.SHEmptyRecycleBinW(parent_hwnd, root_path, flags)
        except Exception:
            return RecycleBinResult('failed', '清空回收站失败。')
        code = _hresult(result)
        if code == 0:
            return RecycleBinResult('completed')
        if code in {_ERROR_CANCELLED, _E_ABORT}:
            return RecycleBinResult('cancelled', '已取消清空回收站。')
        return RecycleBinResult('failed', '清空回收站失败。')


def _hresult(value: object) -> int:
    return int(value) & 0xFFFFFFFF
