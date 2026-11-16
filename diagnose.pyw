# -*- coding: utf-8 -*-
"""双击即出诊断报告（无控制台）。

打包成 KeyMouseBattery-diagnose.exe 后，双击会：
  1. 弹窗显示完整诊断内容（可直接截图）
  2. 同时把报告写到 %LOCALAPPDATA%\KeyMouseBattery\diagnose.txt 并用记事本打开
"""
import sys

import battery_tray

if __name__ == "__main__":
    sys.argv = [sys.argv[0], "--diagnose"]
    sys.exit(battery_tray.main())
