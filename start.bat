@echo off
cd /d "%~dp0"
set PORT=8848
set PY=C:\Users\73873\.workbuddy\binaries\python\versions\3.13.12\python.exe
if not exist "%PY%" set PY=python
echo Starting Touyan Workbench on port %PORT% ...
echo (Browser will open automatically once the server is ready)
echo (财务分析 / 估值模型 / 策略回测 均为内嵌工具页，随工作台一起打开)
start "" /min powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 2; Start-Process 'http://localhost:%PORT%/index.html'"
"%PY%" "05-行业与个股分析/财务分析/工具/stock_analyzer.py" --serve %PORT%