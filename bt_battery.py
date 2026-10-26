# -*- coding: utf-8 -*-
"""bt_battery.py —— 读取 Windows 给蓝牙设备记录的电量

原理
----
蓝牙（BLE）键鼠、耳机通过 GATT 的 Battery Service 上报电量，Windows 蓝牙栈
收到后把它写进设备节点上的一个未公开 PnP 属性：

    PROPERTYKEY {104EA319-6EE2-4701-BD47-8DDBF425BBE5}, 2
    类型：DEVPROP_TYPE_BYTE    取值：0-100

「设置 → 蓝牙和其他设备」里显示的那个百分比就是这个值。所以本模块读到的是
**真实电量**，不是估算。

注意：
  * 属性挂在设备节点（`BTHLE\\DEV_<MAC>`）上，用 SetupAPI 按实例枚举才能读到；
  * 设备没连上、或本身不实现 Battery Service 时，属性不存在或为 0；
  * 走 2.4G 接收器 / 数据线的设备不在 BLE 列表里，系统根本没有电量可读。
"""
from __future__ import annotations

import ctypes
from dataclasses import dataclass
from typing import Optional

import winapi
from winapi import GUID, PROPERTYKEY, SPDRP_FRIENDLYNAME, setupapi

# 蓝牙电量属性（Windows 未公开）
FMTID_BLUETOOTH = GUID(
    0x104EA319, 0x6EE2, 0x4701,
    (ctypes.c_ubyte * 8)(0xBD, 0x47, 0x8D, 0xDB, 0xF4, 0x25, 0xBB, 0xE5),
)
PID_BATTERY_LEVEL = 2

DEFAULT_ENUMERATOR = "BTHLE"      # 蓝牙低功耗设备节点


@dataclass
class BluetoothDevice:
    name: str
    instance_id: str
    battery: Optional[int] = None
    has_property: bool = False
    reason: str = ""

    @property
    def address(self) -> str:
        """从实例 ID（BTHLE\\DEV_<12 位 MAC>\\...）里取蓝牙地址。"""
        parts = self.instance_id.split("\\")
        for part in parts:
            if part.upper().startswith("DEV_"):
                return part[4:]
        return ""


def read_battery_property(hdev: int, info) -> tuple[Optional[int], bool, str]:
    """读一个设备节点的电量属性，返回 (电量, 属性是否存在, 说明)。"""
    key = PROPERTYKEY(FMTID_BLUETOOTH, PID_BATTERY_LEVEL)
    ptype = ctypes.c_ulong(0)
    value = ctypes.c_ubyte(0)
    need = ctypes.c_ulong(0)
    ok = setupapi.SetupDiGetDevicePropertyW(
        hdev, ctypes.byref(info), ctypes.byref(key), ctypes.byref(ptype),
        ctypes.byref(value), 1, ctypes.byref(need), 0,
    )
    if not ok:
        err = ctypes.get_last_error()
        if err == winapi.ERROR_NOT_FOUND:
            return None, False, "设备没有电量属性（未连接，或不支持 Battery Service）"
        return None, False, "读取失败 err=%d" % err
    level = int(value.value)
    if level == 0:
        return 0, True, "属性存在但为 0（通常表示未连接）"
    return min(100, level), True, "来自 BLE Battery Service"


def list_ble_devices(enumerator: str = DEFAULT_ENUMERATOR) -> list[BluetoothDevice]:
    """枚举 BLE 设备节点并读出各自的电量。"""
    result: list[BluetoothDevice] = []
    hdev = setupapi.SetupDiGetClassDevsW(
        None, enumerator, None, winapi.DIGCF_PRESENT | winapi.DIGCF_ALLCLASSES)
    if not hdev or hdev == winapi.INVALID_HANDLE_VALUE:
        return result
    try:
        info = winapi.new_devinfo()
        index = 0
        while setupapi.SetupDiEnumDeviceInfo(hdev, index, ctypes.byref(info)):
            index += 1
            name = winapi.device_string(hdev, info, SPDRP_FRIENDLYNAME)
            instance = winapi.device_instance_id(hdev, info)
            level, has_prop, reason = read_battery_property(hdev, info)
            result.append(BluetoothDevice(
                name=name, instance_id=instance, battery=level,
                has_property=has_prop, reason=reason))
    finally:
        setupapi.SetupDiDestroyDeviceInfoList(hdev)
    return result


if __name__ == "__main__":
    for dev in list_ble_devices():
        print("%-28s %-6s %s"
              % (dev.name or "(无名)", dev.battery, dev.address))
