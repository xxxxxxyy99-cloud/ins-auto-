@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ==========================================
echo   InsAuto — Instagram Content Automation
echo ==========================================
echo.

:: ---- Check Python ----
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found. Please install Python 3.10+
    echo         https://www.python.org/downloads/
    pause
    exit /b 1
)

:: ---- Create .env template if missing ----
if not exist ".env" (
    echo [INFO] Creating .env template...
    (
        echo OPENROUTER_API_KEY=your-openrouter-api-key-here
        echo IG_USERNAME=your-instagram-username
        echo IG_PASSWORD=your-instagram-password
    ) > .env
    echo [INFO] .env created — edit it with your credentials before posting.
)

:: ---- Install dependencies if needed ----
python -c "import streamlit" >nul 2>&1
if %errorlevel% neq 0 (
    echo [INFO] Installing dependencies...
    pip install -r requirements.txt -q
    if %errorlevel% neq 0 (
        echo [ERROR] pip install failed. Run: pip install -r requirements.txt
        pause
        exit /b 1
    )
    echo [OK] Dependencies installed.
)

echo [OK] Starting Streamlit dashboard...
echo       Open http://localhost:8501 in your browser
echo       Press Ctrl+C to stop.
echo.
streamlit run app.py

pause
