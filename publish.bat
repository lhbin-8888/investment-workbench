@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"
set "PY=C:\Users\73873\.workbuddy\binaries\python\versions\3.13.12\python.exe"
if not exist "%PY%" set "PY=python"

echo ============================================================
echo   投研工作台 · 一键发布
echo   自动提交本地改动并推送到 GitHub Pages + Gitee
echo ============================================================

"%PY%" "tools\publish_workbench.py"

echo.
echo 按任意键关闭窗口...
pause >nul
