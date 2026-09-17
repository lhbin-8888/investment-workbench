@echo off
cd /d "%~dp0"
set PORT=8848
set PY=C:\Users\73873\.workbuddy\binaries\python\versions\3.13.12\python.exe
if not exist "%PY%" set PY=python
echo Starting Touyan Workbench on port %PORT% ...
echo (Browser will open automatically once the server is ready)
echo (估值模型已并入主服务 8848，无需独立端口)
start "" /min powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 2; Start-Process 'http://localhost:%PORT%/index.html'"
"%PY%" "08-财务分析/stock_analyzer.py" --serve %PORT%