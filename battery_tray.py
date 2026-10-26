# -*- coding: utf-8 -*-
"""battery_tray.py —— 键盘 + 鼠标电量托盘（同一图标交替显示真实百分比）

设备（改 DEVICE_SPECS 即可换键鼠）：
    * 键盘：名字含 "TOGAR" / "T9"    → 图标用**大字号**
    * 鼠标：名字含 "EWEADN" / "A7"   → 图标用**小字号**

数据来源：蓝牙 BLE 的 Battery Service。Windows 把它写进 BLE 设备节点的未公开属性
{104EA319-6EE2-4701-BD47-8DDBF425BBE5}, 2 —— 也就是「设置 → 蓝牙和其他设备」
里显示的那个百分比，所以是真实值，不是估算。

配色：10 档（每 10% 一档）
    51-100% → 5 种绿，越浅电量越低；0-50% → 5 种红，越深电量越低

用法：
    pythonw battery_tray.py            静默驻留
    python  battery_tray.py --debug    前台运行并打印
    python  battery_tray.py --once     读一次打印 JSON
    python  battery_tray.py --quit     让托盘退出
    python  battery_tray.py --switch 5 切换间隔改成 5 秒
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import sys
import threading
import time
from ctypes import wintypes
from typing import Optional

import bt_battery
import win_icon

try:
    import winreg
except ImportError:      # 非 Windows 环境仅用于静态检查
    winreg = None

# 打包成 exe 后 __file__ 指向临时解包目录，必须用 exe 自身所在目录
FROZEN = bool(getattr(sys, "frozen", False))
BASE_DIR = (os.path.dirname(os.path.abspath(sys.executable)) if FROZEN
            else os.path.dirname(os.path.abspath(__file__)))
STATE_DIR = os.path.join(
    os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "KeyMouseBattery")
STATE_FILE = os.path.join(STATE_DIR, "state.json")
APP_NAME = "键鼠电量"
MUTEX_NAME = "Local\\KeyMouseBatteryTray"
WND_CLASS = "KeyMouseBatteryTray"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "KeyMouseBatteryTray"

LOW_BATTERY = 5               # 低于这个百分比就弹通知（每天最多一次）

REFRESH_SECONDS = 30          # 电量重新读取间隔
DEFAULT_SWITCH_SECONDS = 3    # 键盘/鼠标切换间隔

# 本人的设备（名字命中就用 键盘/鼠标 这两个友好标签，并固定字号）
DEVICE_SPECS = [
    {"key": "kbd", "label": "键盘", "hints": ("togar", "t9"), "big": True},
    {"key": "mouse", "label": "鼠标", "hints": ("eweadn", "a7"), "big": False},
]

# 别人用其他品牌时：只要 BLE 设备报了电量，就自动列出来（最多 4 个）
MAX_DEVICES = 4
KB_HINTS = ("keyboard", "键盘", "keychron", "kbd", "kb-", " k8", " k3")
MOUSE_HINTS = ("mouse", "鼠标", "mice", "mx master", "mx anywhere")

# 10 档配色：51-100% 绿色（浅→深 = 低→高）
GREEN_SHADES = [
    (160, 230, 170),   # 第 6 档 51-60%（最浅）
    (118, 214, 138),   # 第 7 档 61-70%
    (82, 194, 108),    # 第 8 档 71-80%
    (52, 168, 84),     # 第 9 档 81-90%
    (32, 142, 62),     # 第 10 档 91-100%（最深）
]
# 0-50% 红色（浅→深 = 高→低）
RED_SHADES = [
    (240, 160, 160),   # 第 5 档 41-50%（最浅）
    (232, 124, 124),   # 第 4 档 31-40%
    (220, 92, 92),     # 第 3 档 21-30%
    (204, 62, 62),     # 第 2 档 11-20%
    (184, 38, 38),     # 第 1 档 0-10%（最深）
]
UNKNOWN_COLOR = (150, 155, 160)


# --------------------------------------------------------------------------
# 档位与配色
# --------------------------------------------------------------------------
def level_band(level: Optional[int]) -> Optional[int]:
    """电量 → 档位 1..10（每 10% 一档）。"""
    if level is None:
        return None
    return max(1, min(10, (int(level) + 9) // 10))


def level_color(level: Optional[int]) -> tuple[int, int, int]:
    band = level_band(level)
    if band is None:
        return UNKNOWN_COLOR
    if band >= 6:
        return GREEN_SHADES[band - 6]
    return RED_SHADES[5 - band]


def _icon_text(level: Optional[int]) -> str:
    return str(level) if level is not None else "?"


# --------------------------------------------------------------------------
# 读取电量
# --------------------------------------------------------------------------
def _guess_big(name: str) -> bool:
    """名字像键盘就用大字号，其余（鼠标/耳机等）用小字号。"""
    low = (name or "").lower()
    if any(h in low for h in MOUSE_HINTS):
        return False
    return any(h in low for h in KB_HINTS)


def _entry(label: str, device: str, level, big: bool) -> dict:
    return {"key": "dev:" + (device or label), "label": label,
            "device": device, "level": level, "big": big}


def read_batteries() -> list[dict]:
    """读所有 BLE 设备电量。

    1. 先按 DEVICE_SPECS 匹配自己的键鼠（用「键盘/鼠标」标签 + 固定字号）
    2. 剩下的、能读出电量的设备也自动列出来（其他人的键盘鼠标照样显示）
    """
    try:
        devices = [d for d in bt_battery.list_ble_devices()
                   if d.battery is not None and 0 <= d.battery <= 100]
    except Exception:  # noqa: BLE001
        devices = []

    used: set[int] = set()
    entries: list[dict] = []

    for spec in DEVICE_SPECS:
        best = None
        for idx, dev in enumerate(devices):
            if idx in used:
                continue
            low = (dev.name or "").lower()
            if not any(hint in low for hint in spec["hints"]):
                continue
            if best is None or dev.battery > devices[best].battery:
                best = idx
        if best is None:
            continue
        used.add(best)
        dev = devices[best]
        entries.append(_entry(spec["label"], dev.name.strip(), int(dev.battery),
                              bool(spec.get("big", True))))

    # 没被预置规则占用的设备（其他品牌）
    for idx, dev in enumerate(devices):
        if idx in used:
            continue
        name = (dev.name or "").strip() or "蓝牙设备"
        label = name if len(name) <= 12 else name[:11] + "…"
        entries.append(_entry(label, name, int(dev.battery), _guess_big(name)))

    if not entries:
        # 一个都没读到：保留两个占位，提示未连上
        entries = [_entry(s["label"], "", None, bool(s.get("big", True)))
                   for s in DEVICE_SPECS[:2]]
    return entries[:MAX_DEVICES]


# --------------------------------------------------------------------------
# 通知频率（每天最多一次，跨重启也有效）
# --------------------------------------------------------------------------
def _load_state() -> dict:
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _save_state(data: dict) -> None:
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)
        os.replace(tmp, STATE_FILE)
    except Exception:  # noqa: BLE001
        pass


def notified_today() -> bool:
    return _load_state().get("last_notify_date") == time.strftime("%Y-%m-%d")


def mark_notified_today() -> None:
    state = _load_state()
    state["last_notify_date"] = time.strftime("%Y-%m-%d")
    _save_state(state)


# --------------------------------------------------------------------------
# 开机自启
# --------------------------------------------------------------------------
def launch_command() -> str:
    """开机自启要执行的命令：exe 版直接跑自己，脚本版用 pythonw 跑 .py。"""
    if FROZEN:
        return '"%s"' % sys.executable
    return '"%s" "%s"' % (_pythonw(), os.path.join(BASE_DIR,
                                                   "battery_tray.py"))


def _pythonw() -> str:
    exe = sys.executable or "pythonw.exe"
    cand = os.path.join(os.path.dirname(exe), "pythonw.exe")
    return cand if os.path.exists(cand) else exe


def autostart_enabled() -> bool:
    if winreg is None:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, RUN_VALUE)
        return True
    except OSError:
        return False


def set_autostart(enabled: bool) -> bool:
    if winreg is None:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                            winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, RUN_VALUE, 0, winreg.REG_SZ,
                                  launch_command())
            else:
                try:
                    winreg.DeleteValue(key, RUN_VALUE)
                except FileNotFoundError:
                    pass
        return True
    except OSError:
        return False


# --------------------------------------------------------------------------
# Win32
# --------------------------------------------------------------------------
USER32 = ctypes.WinDLL("user32", use_last_error=True)
KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
SHELL32 = ctypes.WinDLL("shell32", use_last_error=True)

WM_DESTROY = 0x0002
WM_TIMER = 0x0113
WM_COMMAND = 0x0111
WM_LBUTTONUP = 0x0202
WM_RBUTTONUP = 0x0205
WM_APP = 0x8000
MSG_TRAY_CALLBACK = WM_APP + 1
MSG_REFRESH_DONE = WM_APP + 2

NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP = 0x01, 0x02, 0x04
NIF_INFO = 0x10
NIIF_INFO, NIIF_WARNING = 0x01, 0x02

MF_STRING, MF_SEPARATOR, MF_GRAYED, MF_POPUP = 0x0000, 0x0800, 0x0001, 0x0010
MF_CHECKED = 0x0008
TPM_RIGHTBUTTON, TPM_NONOTIFY, TPM_RETURNCMD = 0x0002, 0x0080, 0x0100

ID_REFRESH = 1001
ID_SPEED_BASE = 1100
SPEEDS = (2, 3, 5)
ID_AUTOSTART = 1200
ID_TEST_NOTIFY = 1250
ID_QUIT = 1300

WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_void_p, ctypes.c_uint,
                             ctypes.c_size_t, ctypes.c_ssize_t)


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT), ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int), ("hInstance", ctypes.c_void_p),
        ("hIcon", ctypes.c_void_p), ("hCursor", ctypes.c_void_p),
        ("hbrBackground", ctypes.c_void_p), ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR), ("hIconSm", ctypes.c_void_p),
    ]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD), ("hWnd", ctypes.c_void_p),
        ("uID", wintypes.UINT), ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT), ("hIcon", ctypes.c_void_p),
        ("szTip", ctypes.c_wchar * 128), ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD), ("szInfo", ctypes.c_wchar * 256),
        ("uVersion", wintypes.UINT), ("szInfoTitle", ctypes.c_wchar * 64),
        ("dwInfoFlags", wintypes.DWORD), ("guidItem", GUID),
        ("hBalloonIcon", ctypes.c_void_p),
    ]


class MSG(ctypes.Structure):
    _fields_ = [("hWnd", ctypes.c_void_p), ("message", wintypes.UINT),
                ("wParam", ctypes.c_size_t), ("lParam", ctypes.c_ssize_t),
                ("time", wintypes.DWORD), ("pt_x", wintypes.LONG),
                ("pt_y", wintypes.LONG)]


USER32.RegisterClassExW.restype = wintypes.WORD
USER32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
USER32.CreateWindowExW.restype = ctypes.c_void_p
USER32.CreateWindowExW.argtypes = [
    wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
USER32.DefWindowProcW.restype = ctypes.c_ssize_t
USER32.DefWindowProcW.argtypes = [ctypes.c_void_p, wintypes.UINT,
                                  ctypes.c_size_t, ctypes.c_ssize_t]
USER32.SetTimer.restype = ctypes.c_size_t
USER32.SetTimer.argtypes = [ctypes.c_void_p, ctypes.c_size_t, wintypes.UINT,
                            ctypes.c_void_p]
USER32.GetMessageW.restype = ctypes.c_int
USER32.GetMessageW.argtypes = [ctypes.POINTER(MSG), ctypes.c_void_p,
                               wintypes.UINT, wintypes.UINT]
USER32.TranslateMessage.argtypes = [ctypes.POINTER(MSG)]
USER32.DispatchMessageW.restype = ctypes.c_ssize_t
USER32.DispatchMessageW.argtypes = [ctypes.POINTER(MSG)]
USER32.PostQuitMessage.restype = None
USER32.CreatePopupMenu.restype = ctypes.c_void_p
USER32.AppendMenuW.restype = wintypes.BOOL
USER32.AppendMenuW.argtypes = [ctypes.c_void_p, wintypes.UINT,
                               ctypes.c_size_t, wintypes.LPCWSTR]
USER32.TrackPopupMenu.restype = ctypes.c_int
USER32.TrackPopupMenu.argtypes = [ctypes.c_void_p, wintypes.UINT,
                                  ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                  ctypes.c_void_p, ctypes.c_void_p]
USER32.DestroyMenu.argtypes = [ctypes.c_void_p]
USER32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
USER32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
USER32.PostMessageW.argtypes = [ctypes.c_void_p, wintypes.UINT,
                                ctypes.c_size_t, ctypes.c_ssize_t]
USER32.RegisterWindowMessageW.restype = wintypes.UINT
USER32.RegisterWindowMessageW.argtypes = [wintypes.LPCWSTR]
USER32.FindWindowW.restype = ctypes.c_void_p
USER32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]

SHELL32.Shell_NotifyIconW.restype = wintypes.BOOL
SHELL32.Shell_NotifyIconW.argtypes = [wintypes.DWORD,
                                      ctypes.POINTER(NOTIFYICONDATAW)]
KERNEL32.GetModuleHandleW.restype = ctypes.c_void_p
KERNEL32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
KERNEL32.CreateMutexW.restype = ctypes.c_void_p
KERNEL32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL,
                                  wintypes.LPCWSTR]


# --------------------------------------------------------------------------
class TrayApp:
    def __init__(self, debug: bool = False,
                 switch_seconds: int = DEFAULT_SWITCH_SECONDS):
        self.debug = debug
        self.switch_seconds = max(1, switch_seconds)
        self.hwnd: Optional[int] = None
        self.wndproc_ref = None
        self.busy = False
        self.batteries: list[dict] = [
            {"key": s["key"], "label": s["label"], "device": "", "level": None}
            for s in DEVICE_SPECS]
        self.index = 0
        self.tick = 0
        self.icon_added = False
        self.taskbar_created = USER32.RegisterWindowMessageW("TaskbarCreated")

    def log(self, msg: str) -> None:
        if self.debug:
            print("%s %s" % (time.strftime("%H:%M:%S"), msg), flush=True)

    # ---- 图标 --------------------------------------------------------
    def _nid(self) -> NOTIFYICONDATAW:
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self.hwnd
        nid.uID = 1
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = MSG_TRAY_CALLBACK
        return nid

    def _current(self) -> dict:
        if not self.batteries:
            return {"key": "kbd", "label": "设备", "level": None}
        return self.batteries[self.index % len(self.batteries)]

    def _tooltip(self) -> str:
        parts = []
        for item in self.batteries:
            if item["level"] is None:
                parts.append("%s：未连上" % item["label"])
            else:
                parts.append("%s %d%%（%d/10 档）"
                             % (item["label"], item["level"],
                                level_band(item["level"])))
        cur = self._current()
        return "%s · 当前显示：%s（%d 秒切换）" % (
            " · ".join(parts), cur["label"], self.switch_seconds)

    def apply_icon(self, action: int) -> None:
        cur = self._current()
        nid = self._nid()
        nid.hIcon = win_icon.make_hicon_digit(
            _icon_text(cur["level"]), level_color(cur["level"]),
            small=not bool(cur.get("big", True)))
        nid.szTip = self._tooltip()
        ok = SHELL32.Shell_NotifyIconW(action, ctypes.byref(nid))
        self.log("icon %s -> %s (%s %s%%, band %s)"
                 % (action, "ok" if ok else "fail", cur["label"],
                    cur["level"], level_band(cur["level"])))

    def update_icon(self) -> None:
        if not self.icon_added:
            self.apply_icon(NIM_ADD)
            self.icon_added = True
        else:
            self.apply_icon(NIM_MODIFY)

    # ---- 低电量通知 --------------------------------------------------
    def notify(self, text: str, title: str = "键鼠电量") -> None:
        """托盘气泡通知（Win10/11 会进通知中心）。"""
        nid = self._nid()
        nid.uFlags = NIF_INFO | NIF_ICON | NIF_TIP
        nid.hIcon = win_icon.make_hicon_digit(
            _icon_text(self._current()["level"]),
            level_color(self._current()["level"]))
        nid.szTip = self._tooltip()
        nid.szInfoTitle = title[:63]
        nid.szInfo = text[:255]
        nid.dwInfoFlags = NIIF_WARNING
        ok = SHELL32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))
        self.log("notify %r -> %s" % (text, "ok" if ok else "fail"))

    def check_low_battery(self) -> None:
        """任一设备低于 LOW_BATTERY 时提醒；**每台电脑每天最多弹一次**。"""
        lows = [item for item in self.batteries
                if item["level"] is not None and item["level"] < LOW_BATTERY]
        if not lows:
            return
        if notified_today():
            self.log("今天已经提醒过了，跳过")
            return
        if len(lows) == 1:
            item = lows[0]
            text = "电量低，该给%s充电了（%s 剩 %d%%）" % (
                item["label"], item["device"] or item["label"], item["level"])
        else:
            parts = "、".join("%s %d%%" % (i["label"], i["level"]) for i in lows)
            text = "电量低，该给%s充电了" % parts
        self.notify(text)
        mark_notified_today()

    def remove_icon(self) -> None:
        if not self.icon_added:
            return
        nid = self._nid()
        nid.uFlags = 0
        SHELL32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))
        self.icon_added = False

    # ---- 刷新 --------------------------------------------------------
    def refresh_now(self) -> None:
        if self.busy:
            return
        self.busy = True
        threading.Thread(target=self._worker, args=(self.hwnd,),
                         daemon=True).start()

    def _worker(self, hwnd: int) -> None:
        try:
            data = read_batteries()
        except Exception as exc:  # noqa: BLE001
            self.log("读取失败：%s" % exc)
            data = self.batteries
        self.batteries = data
        self.busy = False
        self.log("refresh -> %s" % [(d["label"], d["level"]) for d in data])
        if hwnd:
            USER32.PostMessageW(hwnd, MSG_REFRESH_DONE, 0, 0)

    # ---- 菜单 --------------------------------------------------------
    def show_menu(self) -> None:
        menu = USER32.CreatePopupMenu()
        for item in self.batteries:
            if item["level"] is None:
                text = "%s %s：未连上" % (item["label"],
                                          item["device"] or "（未识别）")
            else:
                text = "%s %s：%d%%（第 %d/10 档）" % (
                    item["label"], item["device"] or "（未识别）",
                    item["level"], level_band(item["level"]))
            USER32.AppendMenuW(menu, MF_STRING | MF_GRAYED, 0, text)
        USER32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        USER32.AppendMenuW(menu, MF_STRING, ID_REFRESH, "立即刷新")
        sub = USER32.CreatePopupMenu()
        for idx, sec in enumerate(SPEEDS):
            flags = MF_STRING | (MF_CHECKED if sec == self.switch_seconds else 0)
            USER32.AppendMenuW(sub, flags, ID_SPEED_BASE + idx,
                               "每 %d 秒切换" % sec)
        USER32.AppendMenuW(menu, MF_POPUP, sub, "切换间隔")
        auto = MF_STRING | (MF_CHECKED if autostart_enabled() else 0)
        USER32.AppendMenuW(menu, auto, ID_AUTOSTART, "开机自启")
        tip = "测试低电量通知（今天%s）" % ("已提醒过" if notified_today() else "还没提醒")
        USER32.AppendMenuW(menu, MF_STRING, ID_TEST_NOTIFY, tip)
        USER32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        USER32.AppendMenuW(menu, MF_STRING, ID_QUIT, "退出")

        pt = wintypes.POINT()
        USER32.GetCursorPos(ctypes.byref(pt))
        USER32.SetForegroundWindow(self.hwnd)
        cmd = USER32.TrackPopupMenu(
            menu, TPM_RIGHTBUTTON | TPM_RETURNCMD | TPM_NONOTIFY,
            pt.x, pt.y, 0, self.hwnd, None)
        USER32.DestroyMenu(menu)
        self.on_command(cmd)

    def on_command(self, cmd: int) -> None:
        if cmd == ID_REFRESH:
            self.refresh_now()
        elif ID_SPEED_BASE <= cmd < ID_SPEED_BASE + len(SPEEDS):
            self.switch_seconds = SPEEDS[cmd - ID_SPEED_BASE]
            self.tick = 0
            self.update_icon()
        elif cmd == ID_TEST_NOTIFY:
            self.notify("电量低，该给键盘充电了（这是测试通知）")
        elif cmd == ID_AUTOSTART:
            set_autostart(not autostart_enabled())
        elif cmd == ID_QUIT:
            self.quit()

    # ---- 生命周期 ----------------------------------------------------
    def quit(self) -> None:
        USER32.KillTimer(self.hwnd, 1)
        self.remove_icon()
        win_icon.destroy_all()
        if self.hwnd:
            USER32.DestroyWindow(self.hwnd)

    def wnd_proc(self, hwnd, msg, wparam, lparam):
        if msg == WM_COMMAND:
            self.on_command(int(wparam or 0))
            return 0
        if msg == MSG_TRAY_CALLBACK:
            if lparam == WM_LBUTTONUP:
                self.refresh_now()
            elif lparam == WM_RBUTTONUP:
                self.show_menu()
            return 0
        if msg == MSG_REFRESH_DONE:
            self.update_icon()
            self.check_low_battery()
            return 0
        if msg == WM_TIMER:
            self.on_tick()
            return 0
        if msg == self.taskbar_created and self.taskbar_created:
            self.icon_added = False
            self.update_icon()
            return 0
        if msg == WM_DESTROY:
            self.remove_icon()
            USER32.PostQuitMessage(0)
            return 0
        return USER32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def on_tick(self) -> None:
        self.tick += 1
        if self.tick % self.switch_seconds == 0:
            if len(self.batteries) > 1:
                self.index = (self.index + 1) % len(self.batteries)
            self.update_icon()
        if self.tick % REFRESH_SECONDS == 0:
            self.refresh_now()

    def run(self) -> int:
        hinst = KERNEL32.GetModuleHandleW(None)
        wc = WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
        wc.lpfnWndProc = WNDPROC(self.wnd_proc)
        self.wndproc_ref = wc.lpfnWndProc
        wc.hInstance = hinst
        wc.lpszClassName = WND_CLASS
        if not USER32.RegisterClassExW(ctypes.byref(wc)):
            if ctypes.get_last_error() != 1410:
                print("RegisterClassExW 失败 err=%d" % ctypes.get_last_error(),
                      file=sys.stderr)
                return 1
        self.hwnd = USER32.CreateWindowExW(0, WND_CLASS, APP_NAME, 0,
                                           0, 0, 0, 0, None, None, hinst, None)
        if not self.hwnd:
            print("CreateWindowExW 失败 err=%d" % ctypes.get_last_error(),
                  file=sys.stderr)
            return 1
        self.update_icon()
        self.refresh_now()
        USER32.SetTimer(self.hwnd, 1, 1000, None)
        msg = MSG()
        while USER32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            USER32.TranslateMessage(ctypes.byref(msg))
            USER32.DispatchMessageW(ctypes.byref(msg))
        return 0


def already_running() -> bool:
    handle = KERNEL32.CreateMutexW(None, True, MUTEX_NAME)
    if not handle:
        return False
    return ctypes.get_last_error() == 183


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--debug", action="store_true")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--quit", action="store_true")
    ap.add_argument("--switch", type=int, default=DEFAULT_SWITCH_SECONDS,
                    help="切换间隔秒数（默认 3）")
    ap.add_argument("--test-notify", action="store_true",
                    help="立刻弹一条低电量通知（测试用）")
    ap.add_argument("--install-autostart", action="store_true")
    ap.add_argument("--remove-autostart", action="store_true")
    args = ap.parse_args()

    if args.install_autostart:
        print("开机自启：", "已开启" if set_autostart(True) else "失败")
        return 0
    if args.remove_autostart:
        print("开机自启：", "已关闭" if set_autostart(False) else "失败")
        return 0
    if args.test_notify:
        hwnd = USER32.FindWindowW(WND_CLASS, APP_NAME)
        if not hwnd:
            print("托盘没在运行")
            return 1
        USER32.PostMessageW(hwnd, WM_COMMAND, ID_TEST_NOTIFY, 0)
        print("已请求弹一条测试通知")
        return 0

    if args.once:
        print(json.dumps(read_batteries(), ensure_ascii=True))
        return 0
    if args.quit:
        hwnd = USER32.FindWindowW(WND_CLASS, APP_NAME)
        if hwnd:
            USER32.PostMessageW(hwnd, WM_COMMAND, ID_QUIT, 0)
        return 0
    if already_running():
        print("已经在运行（托盘里找 %s）" % APP_NAME)
        return 0
    return TrayApp(debug=args.debug, switch_seconds=args.switch).run()


if __name__ == "__main__":
    sys.exit(main())
