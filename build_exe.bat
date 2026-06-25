@echo off
cd /d "%~dp0"
py -m pip install pyinstaller
py -m PyInstaller --onefile --windowed --name PlanningManager Base\app_v25_planner.py
pause
