@echo off
setlocal
cd /d "%~dp0..\.."
py -3 -m quant.stock_selector.run --offline
if errorlevel 1 pause
endlocal
