"""Windows autostart management via registry."""

import sys
import winreg

from opencareyes.constants import AUTOSTART_REG_KEY, AUTOSTART_REG_NAME


def is_autostart_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_REG_KEY, 0, winreg.KEY_READ) as key:
            winreg.QueryValueEx(key, AUTOSTART_REG_NAME)
            return True
    except FileNotFoundError:
        return False


def enable_autostart():
    if getattr(sys, "frozen", False):
        exe = f'"{sys.executable}"'
    else:
        exe = f'"{sys.executable}" -m opencareyes'
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_REG_KEY, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, AUTOSTART_REG_NAME, 0, winreg.REG_SZ, exe)


def disable_autostart():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_REG_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, AUTOSTART_REG_NAME)
    except FileNotFoundError:
        pass
