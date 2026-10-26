# 键鼠电量 · KeyMouseBattery

[![Python](https://img.shields.io/badge/Python-3.9%2B-3776AB?logo=python&logoColor=white)](#)
[![Windows](https://img.shields.io/badge/Windows-10%20%2F%2011-0078D4?logo=windows&logoColor=white)](#)
[![Dependencies](https://img.shields.io/badge/dependencies-none-brightgreen)](#)
[![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

一个 Windows 托盘小工具：**在同一个图标里轮换显示蓝牙键盘和蓝牙鼠标的真实电量**，
纯 Python 标准库 + `ctypes`，零第三方依赖，不联网、不写日志。

> A tiny Windows tray app that shows the **real battery level** of your Bluetooth
> keyboard and mouse, alternating in one icon. Stdlib + `ctypes` only.

```
   ┌────┐  3 秒后  ┌────┐
   │ 53 │  ────▶  │ 27 │
   └────┘         └────┘
   键盘(大字)      鼠标(小字)
```

## 特点

- **真实电量**，不是估算：直接读 Windows 为 BLE 设备记录的电量属性，
  与「设置 → 蓝牙和其他设备」显示的数字同源
- **一个图标搞定两台设备**：每 3 秒切换（可调 2/3/5 秒），靠**字号**区分
  —— 键盘大字号、鼠标小字号
- **10 档配色**：51–100% 用 5 种绿（越浅电量越低），0–50% 用 5 种红（越深电量越低）
- **低电量通知**：任一设备低于 5% 弹一次通知，每台电脑每天最多一次
- **任意品牌都能用**：不写死型号，只要 BLE 设备上报电量就会自动列出来（最多 4 台）
- 数字图标是**自己画的点阵字体**（宽体 5×7 / 竖长 3×7 / 紧凑 3×5 自动挑选），
  不依赖 Pillow，也不用系统字体
- 支持打包成**单文件 exe**，拷到没装 Python 的电脑也能直接跑

## 预览

| 键盘（大字） | 鼠标（小字） |
|---|---|
| ![keyboard](preview/icon_keyboard_32.png) | ![mouse](preview/icon_mouse_32.png) |

10 档配色（从 95% 到 5%）：

![bands](preview/bands.png)

## 配色规则

每 10% 一档，共 10 档：

| 档 | 电量 | 颜色 | 色值 |
|---|---|---|---|
| 10 | 91–100% | 深绿 | `#208E3E` |
| 9 | 81–90% | 绿 | `#34A854` |
| 8 | 71–80% | 中绿 | `#52C26C` |
| 7 | 61–70% | 浅绿 | `#76D68A` |
| 6 | 51–60% | 最浅绿 | `#A0E6AA` |
| 5 | 41–50% | 最浅红 | `#F0A0A0` |
| 4 | 31–40% | 浅红 | `#E87C7C` |
| 3 | 21–30% | 红 | `#DC5C5C` |
| 2 | 11–20% | 深红 | `#CC3E3E` |
| 1 | 0–10% | 最深红 | `#B82626` |

图标上显示的是**精确百分比**，颜色表示它落在第几档；悬停提示会写成
`键盘 53%（6/10 档）`。

## 数据从哪来（以及为什么有些设备读不到）

蓝牙 BLE 设备通过 GATT 的 **Battery Service** 上报电量，Windows 蓝牙栈收到后写进
设备节点上的一个未公开 PnP 属性：

```
PROPERTYKEY {104EA319-6EE2-4701-BD47-8DDBF425BBE5}, 2   (DEVPROP_TYPE_BYTE, 0-100)
```

本工具用 SetupAPI 枚举 `BTHLE\DEV_*` 节点并读这个属性，所以拿到的是系统里那个真值。

| 连接方式 | 能否显示 | 原因 |
|---|---|---|
| 蓝牙 BLE（键鼠 / 耳机 / 手柄） | ✅ | 系统里有电量属性 |
| 2.4G 接收器（USB dongle） | ❌ | 接收器不把电量交给系统（实测某把 2.4G 键盘的厂商通道里根本没有电量命令） |
| USB 数据线 | ❌ | 有线供电，系统不报电量 |
| 老式经典蓝牙（非 BLE） | ⚠️ | 多数不实现 Battery Service |

**判断方法**：看「设置 → 蓝牙和其他设备」里有没有百分比。有，本工具就有。

## 快速开始

### 方式一：直接用 exe

到 [Releases](../../releases) 下载 `KeyMouseBattery.exe`，双击即可（不需要装 Python）。
开机自启：托盘图标右键 → 勾上「开机自启」。

### 方式二：跑源码

```bat
pythonw battery_tray.py          :: 静默驻留
python  battery_tray.py --debug  :: 前台运行并打印
python  battery_tray.py --once   :: 读一次，打印 JSON
python  battery_tray.py --quit   :: 让托盘退出
```

### 打包单文件 exe

```bat
pip install pyinstaller
python -m PyInstaller --onefile --noconsole --name "键鼠电量" ^
    --icon app.ico battery_tray.py
```

或直接双击 `build.bat`（会同时生成带控制台的调试版）。

## 操作

| 操作 | 效果 |
|---|---|
| 左键单击图标 | 立即刷新 |
| 右键 | 菜单：两台设备实时电量 / 刷新 / 切换间隔 2·3·5 秒 / 开机自启 / 测试低电量通知 / 退出 |
| 悬停 | `键盘 53%（6/10 档） · 鼠标 27%（3/10 档） · 当前显示：键盘（3 秒切换）` |

电量每 30 秒重读一次，切换只用 1 秒定时器打点，CPU 占用可以忽略。

## 换设备 / 自定义

默认按名字关键字把自己的设备标成「键盘」「鼠标」并固定字号（`battery_tray.py` 顶部）：

```python
DEVICE_SPECS = [
    {"key": "kbd",   "label": "键盘", "hints": ("togar", "t9"),   "big": True},
    {"key": "mouse", "label": "鼠标", "hints": ("eweadn", "a7"),  "big": False},
]
```

没有命中关键字的设备**也会自动列出**（显示真实名字，名字像键盘的用大字号），
所以换品牌一般不用改代码。想固定某台设备的标签/字号，把它的名字片段加进
`DEVICE_SPECS` 即可。先跑一次 `--once` 看系统里识别到的名字。

## 目录结构

```
battery_tray.py       托盘主程序：图标 / 菜单 / 切换 / 通知 / 自启
bt_battery.py         枚举 BLE 设备并读电量属性
winapi.py             只用到的那点 SetupAPI ctypes 声明
win_icon.py           数字图标绘制（点阵字体 + 描边，输出 HICON）
tools/make_icon.py    生成程序图标 app.ico
tools/make_previews.py 生成 README 预览图
app.ico               程序图标
build.bat             一键打包 exe
```

状态文件只有一个，用来记住「今天是否已经提醒过」：

```
%LOCALAPPDATA%\KeyMouseBattery\state.json
```

## 常见问题

**图标显示 `?`**
设备没连上，或者它不通过 BLE 上报电量（2.4G / 有线都不行）。

**数值和系统里显示的不一样**
Windows 的电量值是设备上报时写入的，设备不发新值就不会更新；点一下图标手动刷新试试。

**通知没弹出来**
检查「设置 → 系统 → 通知」里是否允许 Python / 键鼠电量 的通知，并关掉「专注助手」。
也可以用 `python battery_tray.py --test-notify` 手动验证。

**开机自启失效**
自启记录的是绝对路径，挪动 exe 后需要在菜单里取消再勾一次「开机自启」，
或执行 `battery_tray.exe --install-autostart`。

## License

[MIT](LICENSE)
