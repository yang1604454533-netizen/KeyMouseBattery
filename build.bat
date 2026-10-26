@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo [1/3] 生成图标...
python tools\make_icon.py || goto :err

echo [2/3] 打包无控制台版 键鼠电量.exe ...
python -m PyInstaller --onefile --noconsole --name "键鼠电量" ^
    --icon "%~dp0app.ico" --distpath dist --workpath build --specpath build ^
    battery_tray.py || goto :err

echo [3/3] 打包带控制台的调试版...
python -m PyInstaller --onefile --console --name "键鼠电量-调试" ^
    --icon "%~dp0app.ico" --distpath dist --workpath build --specpath build ^
    battery_tray.py || goto :err

echo.
echo 完成，产物在 dist\
dir /b dist
exit /b 0

:err
echo.
echo 打包失败，检查上面的报错。
exit /b 1
