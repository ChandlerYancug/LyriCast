@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
echo 正在诊断...（请先确保音箱正在播放音乐）
echo.
py -3 debug_speaker.py
echo.
echo 结果已保存到 debug_output.txt，把它发给我。
pause
