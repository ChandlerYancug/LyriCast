@echo off
rem LyriCast launcher (Windows).
rem ASCII-only on purpose: non-ASCII bytes in a .bat are parsed with the
rem console codepage and break on some GBK systems.
rem
rem Dependencies live in a project-local virtualenv (.venv), so the system
rem Python installation is never touched. The first run creates .venv and
rem installs requirements.txt; later runs only reinstall when
rem requirements.txt actually changed (MD5 stamp).
rem
rem Launches silently (pythonw, no console). For live logs run
rem run-console.bat, or use the tray menu item "view log" (Notepad).
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"

set "VENV=%CD%\.venv"
set "VPY=%VENV%\Scripts\python.exe"

rem ---- compare requirements.txt against the stamp inside .venv ----
set "HASH="
for /f "skip=1 delims=" %%H in ('certutil -hashfile requirements.txt MD5') do if not defined HASH set "HASH=%%H"
set "OLD="
if exist "%VENV%\lyricast-deps.md5" set /p OLD=<"%VENV%\lyricast-deps.md5"
if not exist "%VPY%" goto setup
if /i not "%HASH%"=="%OLD%" goto setup
goto run

:setup
where py >nul 2>nul
if not errorlevel 1 goto make_py
where python >nul 2>nul
if not errorlevel 1 goto make_python
echo Python not found. Install it from https://www.python.org/downloads/
echo Tick "Add python.exe to PATH" during setup, then run this file again.
pause
exit /b 1

:make_py
if not exist "%VPY%" py -3 -m venv "%VENV%"
goto install

:make_python
if not exist "%VPY%" python -m venv "%VENV%"
goto install

:install
echo Setting up .venv and installing dependencies - first run only, can take a few minutes...
"%VPY%" -m pip install -r requirements.txt --disable-pip-version-check
if errorlevel 1 goto pipfail
> "%VENV%\lyricast-deps.md5" echo %HASH%
goto run

:pipfail
echo.
echo Could not install dependencies - network problem?
echo Try again with a mirror:
echo   "%VPY%" -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
echo If it keeps failing, delete the .venv folder and run this file again.
pause
exit /b 1

:run
if /i "%~1"=="console" goto run_console
start "" "%VENV%\Scripts\pythonw.exe" main.py
exit /b 0

:run_console
"%VPY%" main.py
if errorlevel 1 (
    echo.
    echo [LyriCast exited with an error] See the messages above, and the log at:
    echo   %LOCALAPPDATA%\LyriCast\logs\lyricast.log
    echo Send them to the developer if it keeps failing.
    pause
)
