@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 로봇 바리스타 조종 프로그램을 엽니다. 창을 닫으면 끝납니다.
start "" .venv\Scripts\pythonw.exe programs\barista\app.py
