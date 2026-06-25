@echo off
cd /d "%USERPROFILE%\Downloads"

py -m pip install ttkbootstrap tkcalendar
py app_v25_planner.py

pause
