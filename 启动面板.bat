@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ========================================
echo  AI Instagram Automation Dashboard
echo ========================================
echo.
echo Starting dashboard...
echo.
streamlit run app.py
if %errorlevel% neq 0 (
    echo.
    echo Failed to start. Make sure Streamlit is installed:
    echo pip install streamlit
    pause
)
