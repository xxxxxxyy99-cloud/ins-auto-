@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"

echo ==========================================
echo   InsAuto Scheduler
echo   (close this window to stop)
echo ==========================================
echo.

where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found
    pause
    exit /b 1
)

python scheduler.py
pause
