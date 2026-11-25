@echo off
setlocal
cd /d "%~dp0..\.."
py -3 -m quant.stock_selector.daily_update
set CODE=%ERRORLEVEL%
if not "%CODE%"=="0" pause
exit /b %CODE%
