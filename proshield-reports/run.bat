@echo off
echo ================================================
echo   Proshield Reports - Field Reporting System
echo ================================================
echo.

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not in PATH
    echo Please install Python 3.9+ from https://python.org
    pause
    exit /b 1
)

REM Check if virtual environment exists
if not exist "venv" (
    echo [*] Creating virtual environment...
    python -m venv venv
)

REM Activate virtual environment
echo [*] Activating virtual environment...
call venv\Scripts\activate.bat

REM Install dependencies
echo [*] Installing dependencies...
pip install -r requirements.txt --quiet

REM Generate icons if needed
if not exist "static\images\icon-192.png" (
    echo [*] Generating icons...
    python generate_icons.py
)

REM Run the application
echo.
echo [*] Starting Proshield Reports...
echo [*] Open your browser at: http://localhost:5000
echo [*] Default login: rotem / proshield2025
echo.
python run.py

pause
