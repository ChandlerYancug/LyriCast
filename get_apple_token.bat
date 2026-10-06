@echo off
rem Fetch the Apple Music "media-user-token" into am_token.txt.
rem ASCII-only on purpose: non-ASCII bytes in a .bat break on some systems.
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"

if exist "%~dp0.venv\Scripts\python.exe" goto venv
where py >nul 2>nul
if not errorlevel 1 goto pylauncher
echo Python not found. Run run.bat first - it sets everything up.
pause
exit /b 1

:pylauncher
py -3 get_apple_token.py
goto done

:venv
"%~dp0.venv\Scripts\python.exe" get_apple_token.py

:done
echo.
pause
