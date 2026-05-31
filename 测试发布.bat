@echo off
cd /d "%~dp0"

echo Checking...
python --version
echo.

python test_post.py
echo.
echo Exit code: %errorlevel%
pause
