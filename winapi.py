# -*- coding: utf-8 -*-
"""winapi.py —— 只用到的那一点点 Win32/SetupAPI 声明（纯 ctypes）

本项目需要按「设备节点」读一个未公开的 PnP 属性（蓝牙电量），这只能用
SetupAPI 枚举设备 + SetupDiGetDevicePropertyW 来做，ctypes 里没有现成封装，
所以这里手写最小声明：够用就好，不引入 pywin32。
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", GUID), ("pid", wintypes.DWORD)]


class SP_DEVINFO_DATA(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("ClassGuid", GUID),
        ("DevInst", wintypes.DWORD),
        ("Reserved", ctypes.c_void_p),
    ]


# 设备枚举范围
DIGCF_PRESENT = 0x02
DIGCF_ALLCLASSES = 0x04

# 设备注册表属性
SPDRP_DEVICEDESC = 0x00
SPDRP_FRIENDLYNAME = 0x0C

INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
ERROR_NOT_FOUND = 1168

setupapi = ctypes.WinDLL("setupapi", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

setupapi.SetupDiGetClassDevsW.restype = ctypes.c_void_p
setupapi.SetupDiGetClassDevsW.argtypes = [
    ctypes.POINTER(GUID), wintypes.LPCWSTR, ctypes.c_void_p, wintypes.DWORD,
]
setupapi.SetupDiDestroyDeviceInfoList.restype = wintypes.BOOL
setupapi.SetupDiDestroyDeviceInfoList.argtypes = [ctypes.c_void_p]
setupapi.SetupDiEnumDeviceInfo.restype = wintypes.BOOL
setupapi.SetupDiEnumDeviceInfo.argtypes = [
    ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(SP_DEVINFO_DATA),
]
setupapi.SetupDiGetDeviceRegistryPropertyW.restype = wintypes.BOOL
setupapi.SetupDiGetDeviceRegistryPropertyW.argtypes = [
    ctypes.c_void_p, ctypes.POINTER(SP_DEVINFO_DATA), wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p, wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
]
setupapi.SetupDiGetDevicePropertyW.restype = wintypes.BOOL
setupapi.SetupDiGetDevicePropertyW.argtypes = [
    ctypes.c_void_p, ctypes.POINTER(SP_DEVINFO_DATA), ctypes.POINTER(PROPERTYKEY),
    ctypes.POINTER(wintypes.ULONG), ctypes.c_void_p, wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD), wintypes.DWORD,
]
setupapi.SetupDiGetDeviceInstanceIdW.restype = wintypes.BOOL
setupapi.SetupDiGetDeviceInstanceIdW.argtypes = [
    ctypes.c_void_p, ctypes.POINTER(SP_DEVINFO_DATA), wintypes.LPWSTR,
    wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
]


def new_devinfo() -> SP_DEVINFO_DATA:
    info = SP_DEVINFO_DATA()
    info.cbSize = ctypes.sizeof(SP_DEVINFO_DATA)
    return info


def device_string(hdev: int, info: SP_DEVINFO_DATA, prop: int) -> str:
    """读设备的字符串属性（产品名 / 友好名 / 制造商…）。"""
    buf = ctypes.create_string_buffer(1024)
    need = wintypes.DWORD(0)
    if not setupapi.SetupDiGetDeviceRegistryPropertyW(
            hdev, ctypes.byref(info), prop, None, buf, 1024,
            ctypes.byref(need)):
        return ""
    return buf.raw.decode("utf-16-le", errors="ignore").split("\x00")[0]


def device_instance_id(hdev: int, info: SP_DEVINFO_DATA) -> str:
    buf = ctypes.create_unicode_buffer(512)
    need = wintypes.DWORD(0)
    if not setupapi.SetupDiGetDeviceInstanceIdW(
            hdev, ctypes.byref(info), buf, 512, ctypes.byref(need)):
        return ""
    return buf.value
