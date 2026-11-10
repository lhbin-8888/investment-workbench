@echo off
net session > nul 2>&1
if %errorLevel% neq 0 (
    echo Requesting administrator (UAC)...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)
echo === Register AI AutoPick + Weekly scheduled tasks ===
echo [1/2] Daily task TDX_AutoPick (15 fixed --once triggers, ~every 15 min)...
powershell -ExecutionPolicy Bypass -NoProfile -File "%~dp0setup_autopick_task.ps1"
echo.
echo [2/2] Weekly task (every day 15:30)...
powershell -ExecutionPolicy Bypass -NoProfile -File "%~dp0setup_weekly_task.ps1"
echo.
echo Done. Daily AI-pick runs 09:35-14:55 on weekdays; Weekly runs daily 15:30.
echo Check Task Scheduler - Task Scheduler Library for "TDX_AutoPick" and the weekly task.
pause
