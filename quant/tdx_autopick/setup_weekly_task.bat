@echo off
echo Running weekly task setup (powershell)...
powershell -ExecutionPolicy Bypass -NoProfile -File "%~dp0setup_weekly_task.ps1"
pause
