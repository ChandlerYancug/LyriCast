@echo off
rem Diagnostic dump for "cannot read now playing" issues (ASCII-only on purpose).
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
echo Collecting speaker raw data... make sure music is playing.
echo.
py -3 debug_speaker.py
echo.
echo Result saved to debug_output.txt - send it to the developer.
pause
