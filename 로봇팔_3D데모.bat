@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 로봇팔 3D 데모를 엽니다. 창을 닫으면 끝납니다.
set PYTHONIOENCODING=utf-8
.venv\Scripts\python.exe sim\view_demo.py
