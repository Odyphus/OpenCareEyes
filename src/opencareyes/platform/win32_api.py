"""Win32 API declarations via ctypes for display and window management."""

import ctypes
import ctypes.wintypes as wintypes

# ---------------------------------------------------------------------------
# Libraries
# ---------------------------------------------------------------------------
gdi32 = ctypes.windll.gdi32
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
dwmapi = ctypes.windll.dwmapi
shell32 = ctypes.windll.shell32
wtsapi32 = ctypes.windll.wtsapi32

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
MONITOR_DEFAULTTONEAREST = 0x00000002

# Foreground process and physical frame queries
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
DWMWA_EXTENDED_FRAME_BOUNDS = 9

# QUERY_USER_NOTIFICATION_STATE values.  QUNS_QUIET_TIME deliberately maps to
# normal in the context sensor; it is not the Windows 11 Do Not Disturb state.
QUNS_NOT_PRESENT = 1
QUNS_BUSY = 2
QUNS_RUNNING_D3D_FULL_SCREEN = 3
QUNS_PRESENTATION_MODE = 4
QUNS_ACCEPTS_NOTIFICATIONS = 5
QUNS_QUIET_TIME = 6
QUNS_APP = 7

# Session and power messages
WM_POWERBROADCAST = 0x0218
WM_WTSSESSION_CHANGE = 0x02B1
WTS_SESSION_LOCK = 0x7
WTS_SESSION_UNLOCK = 0x8
NOTIFY_FOR_THIS_SESSION = 0
PBT_APMSUSPEND = 0x0004
PBT_APMRESUMECRITICAL = 0x0006
PBT_APMRESUMESUSPEND = 0x0007
PBT_APMRESUMEAUTOMATIC = 0x0012


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


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("dwTime", wintypes.DWORD),
    ]


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", wintypes.POINT),
        ("lPrivate", wintypes.DWORD),
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

CreateDCW = gdi32.CreateDCW
CreateDCW.argtypes = [
    wintypes.LPCWSTR,
    wintypes.LPCWSTR,
    wintypes.LPCWSTR,
    ctypes.c_void_p,
]
CreateDCW.restype = wintypes.HDC

DeleteDC = gdi32.DeleteDC
DeleteDC.argtypes = [wintypes.HDC]
DeleteDC.restype = wintypes.BOOL

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

GetWindowThreadProcessId = user32.GetWindowThreadProcessId
GetWindowThreadProcessId.argtypes = [
    wintypes.HWND,
    ctypes.POINTER(wintypes.DWORD),
]
GetWindowThreadProcessId.restype = wintypes.DWORD

IsIconic = user32.IsIconic
IsIconic.argtypes = [wintypes.HWND]
IsIconic.restype = wintypes.BOOL

GetClassNameW = user32.GetClassNameW
GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
GetClassNameW.restype = ctypes.c_int

MonitorFromWindow = user32.MonitorFromWindow
MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
MonitorFromWindow.restype = wintypes.HMONITOR

GetLastInputInfo = user32.GetLastInputInfo
GetLastInputInfo.argtypes = [ctypes.POINTER(LASTINPUTINFO)]
GetLastInputInfo.restype = wintypes.BOOL

# GetTickCount is intentionally used instead of GetTickCount64 because
# LASTINPUTINFO.dwTime is a 32-bit tick count.  Subtraction is wrap-safe.
GetTickCount = kernel32.GetTickCount
GetTickCount.argtypes = []
GetTickCount.restype = wintypes.DWORD

OpenProcess = kernel32.OpenProcess
OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
OpenProcess.restype = wintypes.HANDLE

QueryFullProcessImageNameW = kernel32.QueryFullProcessImageNameW
QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.LPWSTR,
    ctypes.POINTER(wintypes.DWORD),
]
QueryFullProcessImageNameW.restype = wintypes.BOOL

CloseHandle = kernel32.CloseHandle
CloseHandle.argtypes = [wintypes.HANDLE]
CloseHandle.restype = wintypes.BOOL

DwmGetWindowAttribute = dwmapi.DwmGetWindowAttribute
DwmGetWindowAttribute.argtypes = [
    wintypes.HWND,
    wintypes.DWORD,
    ctypes.c_void_p,
    wintypes.DWORD,
]
DwmGetWindowAttribute.restype = ctypes.c_long

SHQueryUserNotificationState = shell32.SHQueryUserNotificationState
SHQueryUserNotificationState.argtypes = [ctypes.POINTER(ctypes.c_int)]
SHQueryUserNotificationState.restype = ctypes.c_long

WTSRegisterSessionNotification = wtsapi32.WTSRegisterSessionNotification
WTSRegisterSessionNotification.argtypes = [wintypes.HWND, wintypes.DWORD]
WTSRegisterSessionNotification.restype = wintypes.BOOL

WTSUnRegisterSessionNotification = wtsapi32.WTSUnRegisterSessionNotification
WTSUnRegisterSessionNotification.argtypes = [wintypes.HWND]
WTSUnRegisterSessionNotification.restype = wintypes.BOOL

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
