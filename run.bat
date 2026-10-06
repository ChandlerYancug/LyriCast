@echo off
rem LyriCast launcher (Windows).
rem This file is ASCII-only on purpose: non-ASCII bytes in a .bat are parsed
rem with the console codepage and break on some GBK systems.
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"

where py >nul 2>nul
if not errorlevel 1 (
    py -3 main.py
) else (
    where python >nul 2>nul
    if not errorlevel 1 (
        python main.py
    ) else (
        echo Python not found. Install it from https://www.python.org/downloads/
        echo Tick "Add python.exe to PATH" during setup, then run this file again.
        pause
        exit /b 1
    )
)

if errorlevel 1 (
    echo.
    echo [LyriCast exited with an error] See the messages above, and the log at:
    echo   %LOCALAPPDATA%\LyriCast\logs\lyricast.log
    echo Send them to the developer if it keeps failing.
    pause
)
