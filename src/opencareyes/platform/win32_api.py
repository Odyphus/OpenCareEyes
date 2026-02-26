"""Win32 API declarations via ctypes for display and window management."""

import ctypes
import ctypes.wintypes as wintypes

# ---------------------------------------------------------------------------
# Libraries
# ---------------------------------------------------------------------------
gdi32 = ctypes.windll.gdi32
user32 = ctypes.windll.user32

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
# WinEvent constants
EVENT_SYSTEM_FOREGROUND = 0x0003
WINEVENT_OUTOFCONTEXT = 0x0000
WINEVENT_SKIPOWNPROCESS = 0x0002

# SetWindowPos flags
HWND_TOPMOST = wintypes.HWND(-1)
HWND_NOTOPMOST = wintypes.HWND(-2)
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040

# SetLayeredWindowAttributes flags
LWA_ALPHA = 0x00000002
LWA_COLORKEY = 0x00000001

# Window style
GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080

# Monitor info flags
MONITORINFOF_PRIMARY = 0x00000001


# ---------------------------------------------------------------------------
# Structures
# ---------------------------------------------------------------------------
class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", RECT),
        ("rcWork", RECT),
        ("dwFlags", wintypes.DWORD),
        ("szDevice", wintypes.WCHAR * 32),
    ]


# ---------------------------------------------------------------------------
# Callback types
# ---------------------------------------------------------------------------
# BOOL CALLBACK MonitorEnumProc(HMONITOR, HDC, LPRECT, LPARAM)
MONITORENUMPROC = ctypes.WINFUNCTYPE(
    wintypes.BOOL,
    wintypes.HMONITOR,
    wintypes.HDC,
    ctypes.POINTER(RECT),
    wintypes.LPARAM,
)

# void CALLBACK WinEventProc(HWINEVENTHOOK, DWORD, HWND, LONG, LONG, DWORD, DWORD)
WINEVENTPROC = ctypes.WINFUNCTYPE(
    None,
    wintypes.HANDLE,   # hWinEventHook
    wintypes.DWORD,    # event
    wintypes.HWND,     # hwnd
    ctypes.c_long,     # idObject
    ctypes.c_long,     # idChild
    wintypes.DWORD,    # idEventThread
    wintypes.DWORD,    # dwmsEventTime
)

# ---------------------------------------------------------------------------
# Function declarations — Gamma Ramp
# ---------------------------------------------------------------------------
SetDeviceGammaRamp = gdi32.SetDeviceGammaRamp
SetDeviceGammaRamp.argtypes = [wintypes.HDC, ctypes.c_void_p]
SetDeviceGammaRamp.restype = wintypes.BOOL

GetDeviceGammaRamp = gdi32.GetDeviceGammaRamp
GetDeviceGammaRamp.argtypes = [wintypes.HDC, ctypes.c_void_p]
GetDeviceGammaRamp.restype = wintypes.BOOL

# ---------------------------------------------------------------------------
# Function declarations — Display monitor enumeration
# ---------------------------------------------------------------------------
EnumDisplayMonitors = user32.EnumDisplayMonitors
EnumDisplayMonitors.argtypes = [
    wintypes.HDC,
    ctypes.POINTER(RECT),
    MONITORENUMPROC,
    wintypes.LPARAM,
]
EnumDisplayMonitors.restype = wintypes.BOOL

GetMonitorInfoW = user32.GetMonitorInfoW
GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MONITORINFOEXW)]
GetMonitorInfoW.restype = wintypes.BOOL

# ---------------------------------------------------------------------------
# Function declarations — Window event hooks
# ---------------------------------------------------------------------------
SetWinEventHook = user32.SetWinEventHook
SetWinEventHook.argtypes = [
    wintypes.DWORD,    # eventMin
    wintypes.DWORD,    # eventMax
    wintypes.HMODULE,  # hmodWinEventProc
    WINEVENTPROC,      # pfnWinEventProc
    wintypes.DWORD,    # idProcess
    wintypes.DWORD,    # idThread
    wintypes.DWORD,    # dwFlags
]
SetWinEventHook.restype = wintypes.HANDLE

UnhookWinEvent = user32.UnhookWinEvent
UnhookWinEvent.argtypes = [wintypes.HANDLE]
UnhookWinEvent.restype = wintypes.BOOL

GetForegroundWindow = user32.GetForegroundWindow
GetForegroundWindow.argtypes = []
GetForegroundWindow.restype = wintypes.HWND

# ---------------------------------------------------------------------------
# Function declarations — Window attributes
# ---------------------------------------------------------------------------
SetWindowPos = user32.SetWindowPos
SetWindowPos.argtypes = [
    wintypes.HWND,   # hWnd
    wintypes.HWND,   # hWndInsertAfter
    ctypes.c_int,    # X
    ctypes.c_int,    # Y
    ctypes.c_int,    # cx
    ctypes.c_int,    # cy
    wintypes.UINT,   # uFlags
]
SetWindowPos.restype = wintypes.BOOL

SetLayeredWindowAttributes = user32.SetLayeredWindowAttributes
SetLayeredWindowAttributes.argtypes = [
    wintypes.HWND,      # hwnd
    wintypes.COLORREF,  # crKey
    wintypes.BYTE,      # bAlpha
    wintypes.DWORD,     # dwFlags
]
SetLayeredWindowAttributes.restype = wintypes.BOOL

# Window relationship queries
GetWindow = user32.GetWindow
GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
GetWindow.restype = wintypes.HWND

GW_HWNDPREV = 3  # Returns the window above the specified window in Z-order

IsWindow = user32.IsWindow
IsWindow.argtypes = [wintypes.HWND]
IsWindow.restype = wintypes.BOOL

GetWindowLongW = user32.GetWindowLongW
GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
GetWindowLongW.restype = ctypes.c_long

SetWindowLongW = user32.SetWindowLongW
SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
SetWindowLongW.restype = ctypes.c_long

# DC management
GetDC = user32.GetDC
GetDC.argtypes = [wintypes.HWND]
GetDC.restype = wintypes.HDC

ReleaseDC = user32.ReleaseDC
ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
ReleaseDC.restype = ctypes.c_int
