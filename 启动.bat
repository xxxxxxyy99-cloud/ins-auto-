@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"

echo ==========================================
echo   InsAuto Dashboard
echo ==========================================
echo.

where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found
    pause
    exit /b 1
)

python -c "import streamlit" >nul 2>&1
if %errorlevel% neq 0 (
    echo [INFO] Installing deps...
    pip install -r requirements.txt
)

echo [OK] Starting dashboard...
echo      http://localhost:8501
echo.
streamlit run app.py
pause
