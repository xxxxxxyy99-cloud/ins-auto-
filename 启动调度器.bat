@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ==========================================
echo   InsAuto Scheduler — Background Service
echo ==========================================
echo.
echo This window must stay open for the
echo scheduler to run. Minimize it if needed.
echo Press Ctrl+C to stop.
echo.
python scheduler.py
pause
