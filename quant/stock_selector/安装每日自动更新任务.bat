@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_daily_task.ps1"
if errorlevel 1 pause
endlocal
