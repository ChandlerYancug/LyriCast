@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
py -3 main.py
if errorlevel 1 (
    echo.
    echo [程序退出] 上面有原因，照它说的做，或把内容发我。
    pause
)
