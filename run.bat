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
call :fix_pythonw
start "" "%VENV%\Scripts\pythonw.exe" main.py
exit /b 0

rem ---- Python 3.13.0 venv quirk ----
rem Scripts\pythonw.exe is a launcher that starts the console python.exe,
rem so a console window (cmd / Windows Terminal) flashes before the app.
rem Replace it with a plain copy of the base pythonw.exe - a real GUI exe;
rem the venv still applies because pyvenv.cfg sits next to it (sys.prefix ok).
rem Safe to run every time: no-op when the file already matches.
:fix_pythonw
set "PYHOME="
for /f "usebackq tokens=1,* delims== " %%A in (`findstr /b /c:"home" "%VENV%\pyvenv.cfg" 2^>nul`) do if not defined PYHOME set "PYHOME=%%B"
if not defined PYHOME exit /b 0
set "BASEPW=%PYHOME%\pythonw.exe"
if not exist "%BASEPW%" exit /b 0
for %%F in ("%BASEPW%") do if %%~zF LSS 1024 exit /b 0
fc /b "%BASEPW%" "%VENV%\Scripts\pythonw.exe" >nul 2>nul
if not errorlevel 1 exit /b 0
copy /Y "%BASEPW%" "%VENV%\Scripts\pythonw.exe" >nul 2>nul
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
