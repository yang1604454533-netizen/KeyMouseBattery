@echo off
chcp 65001 >nul
cd /d "%~dp0"
set OUT=%~dp0诊断结果.txt

echo KeyMouseBattery 诊断报告 > "%OUT%"
echo 时间: %date% %time% >> "%OUT%"
echo. >> "%OUT%"
echo ==== 系统 ==== >> "%OUT%"
ver >> "%OUT%" 2>&1
wmic os get Caption,Version,OSArchitecture /value 2>nul >> "%OUT%"
echo. >> "%OUT%"
echo ==== 程序自检（新编译版）==== >> "%OUT%"
if exist "%~dp0KeyMouseBattery-debug.exe" (
    "%~dp0KeyMouseBattery-debug.exe" --diagnose >> "%OUT%" 2>&1
) else (
    echo 找不到 KeyMouseBattery-debug.exe >> "%OUT%"
)
echo. >> "%OUT%"
echo ==== 程序自检（兼容版）==== >> "%OUT%"
if exist "%~dp0KeyMouseBattery-debug-compat.exe" (
    "%~dp0KeyMouseBattery-debug-compat.exe" --diagnose >> "%OUT%" 2>&1
) else (
    echo 找不到 KeyMouseBattery-debug-compat.exe >> "%OUT%"
)
echo. >> "%OUT%"
echo ==== 最近错误日志 ==== >> "%OUT%"
if exist "%LOCALAPPDATA%\KeyMouseBattery\error.log" (
    type "%LOCALAPPDATA%\KeyMouseBattery\error.log" >> "%OUT%"
) else (
    echo 没有 error.log（程序没崩过） >> "%OUT%"
)
echo. >> "%OUT%"
echo ==== 进程检查 ==== >> "%OUT%"
tasklist /FI "IMAGENAME eq KeyMouseBattery.exe" >> "%OUT%" 2>&1
tasklist /FI "IMAGENAME eq KeyMouseBattery-compat.exe" >> "%OUT%" 2>&1
tasklist /FI "IMAGENAME eq 键鼠电量.exe" >> "%OUT%" 2>&1

echo 诊断完成，正在打开结果文件……
start "" notepad "%OUT%"
