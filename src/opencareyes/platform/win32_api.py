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
DISPLAY_DEVICE_ACTIVE = 0x00000001
EDD_GET_DEVICE_INTERFACE_NAME = 0x00000001

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
WM_TIMECHANGE = 0x001E
WM_SETTINGCHANGE = 0x001A
WM_DISPLAYCHANGE = 0x007E
WM_HOTKEY = 0x0312
WM_POWERBROADCAST = 0x0218
WM_WTSSESSION_CHANGE = 0x02B1
WTS_SESSION_LOCK = 0x7
WTS_SESSION_UNLOCK = 0x8
NOTIFY_FOR_THIS_SESSION = 0
PBT_APMSUSPEND = 0x0004
PBT_APMRESUMECRITICAL = 0x0006
PBT_APMRESUMESUSPEND = 0x0007
PBT_APMRESUMEAUTOMATIC = 0x0012
TIME_ZONE_ID_INVALID = 0xFFFFFFFF

# RegisterHotKey modifiers
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000


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


class DISPLAY_DEVICEW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("DeviceName", wintypes.WCHAR * 32),
        ("DeviceString", wintypes.WCHAR * 128),
        ("StateFlags", wintypes.DWORD),
        ("DeviceID", wintypes.WCHAR * 128),
        ("DeviceKey", wintypes.WCHAR * 128),
    ]


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("dwTime", wintypes.DWORD),
    ]


class SYSTEMTIME(ctypes.Structure):
    _fields_ = [
        ("wYear", wintypes.WORD),
        ("wMonth", wintypes.WORD),
        ("wDayOfWeek", wintypes.WORD),
        ("wDay", wintypes.WORD),
        ("wHour", wintypes.WORD),
        ("wMinute", wintypes.WORD),
        ("wSecond", wintypes.WORD),
        ("wMilliseconds", wintypes.WORD),
    ]


class DYNAMIC_TIME_ZONE_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("Bias", wintypes.LONG),
        ("StandardName", wintypes.WCHAR * 32),
        ("StandardDate", SYSTEMTIME),
        ("StandardBias", wintypes.LONG),
        ("DaylightName", wintypes.WCHAR * 32),
        ("DaylightDate", SYSTEMTIME),
        ("DaylightBias", wintypes.LONG),
        ("TimeZoneKeyName", wintypes.WCHAR * 128),
        ("DynamicDaylightTimeDisabled", wintypes.BOOLEAN),
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

EnumDisplayDevicesW = user32.EnumDisplayDevicesW
EnumDisplayDevicesW.argtypes = [
    wintypes.LPCWSTR,
    wintypes.DWORD,
    ctypes.POINTER(DISPLAY_DEVICEW),
    wintypes.DWORD,
]
EnumDisplayDevicesW.restype = wintypes.BOOL


def get_display_source_identity(source_name: str) -> tuple[str, ...]:
    """Return stable interface identities for one active GDI display source."""

    source = str(source_name).strip()
    if not source:
        raise OSError("display source name is empty")

    identities: list[str] = []
    index = 0
    while True:
        device = DISPLAY_DEVICEW()
        device.cb = ctypes.sizeof(DISPLAY_DEVICEW)
        if not EnumDisplayDevicesW(
            source,
            index,
            ctypes.byref(device),
            EDD_GET_DEVICE_INTERFACE_NAME,
        ):
            break
        index += 1
        if not bool(device.StateFlags & DISPLAY_DEVICE_ACTIVE):
            continue
        identity = str(device.DeviceID).strip().casefold()
        if not identity:
            raise OSError("active display target has no interface identity")
        identities.append(identity)

    if not identities:
        raise OSError("display source has no active target identity")
    if len(set(identities)) != len(identities):
        raise OSError("display source returned duplicate target identities")
    return tuple(sorted(identities))

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

GetDynamicTimeZoneInformation = kernel32.GetDynamicTimeZoneInformation
GetDynamicTimeZoneInformation.argtypes = [
    ctypes.POINTER(DYNAMIC_TIME_ZONE_INFORMATION)
]
GetDynamicTimeZoneInformation.restype = wintypes.DWORD

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


def get_dynamic_time_zone_fingerprint() -> tuple[object, ...]:
    """Return only the Windows fields that affect local-time scheduling."""

    info = DYNAMIC_TIME_ZONE_INFORMATION()
    result = int(GetDynamicTimeZoneInformation(ctypes.byref(info)))
    if result == TIME_ZONE_ID_INVALID:
        raise OSError("GetDynamicTimeZoneInformation failed")

    def system_time(value: SYSTEMTIME) -> tuple[int, ...]:
        return (
            int(value.wYear),
            int(value.wMonth),
            int(value.wDayOfWeek),
            int(value.wDay),
            int(value.wHour),
            int(value.wMinute),
            int(value.wSecond),
            int(value.wMilliseconds),
        )

    return (
        str(info.TimeZoneKeyName),
        int(info.Bias),
        int(info.StandardBias),
        int(info.DaylightBias),
        bool(info.DynamicDaylightTimeDisabled),
        system_time(info.StandardDate),
        system_time(info.DaylightDate),
    )

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

RegisterHotKey = user32.RegisterHotKey
RegisterHotKey.argtypes = [
    wintypes.HWND,
    ctypes.c_int,
    wintypes.UINT,
    wintypes.UINT,
]
RegisterHotKey.restype = wintypes.BOOL

UnregisterHotKey = user32.UnregisterHotKey
UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
UnregisterHotKey.restype = wintypes.BOOL

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
