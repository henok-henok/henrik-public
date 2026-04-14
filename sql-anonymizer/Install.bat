@echo off
echo ============================================
echo  SQL Anonymizer - Installation
echo ============================================
echo.

REM Check Python version
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH.
    echo Please install Python 3.9 or later from https://python.org
    pause
    exit /b 1
)

REM Check Python version is 3.9+
for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set PYVER=%%v
for /f "tokens=1,2 delims=." %%a in ("%PYVER%") do (
    if %%a LSS 3 (
        echo ERROR: Python 3.9+ required. Found Python %PYVER%
        pause
        exit /b 1
    )
    if %%a EQU 3 if %%b LSS 9 (
        echo ERROR: Python 3.9+ required. Found Python %PYVER%
        pause
        exit /b 1
    )
)
echo Found Python %PYVER%

REM Create or update venv
if not exist "venv" (
    echo Creating virtual environment...
    python -m venv venv
) else (
    echo Virtual environment already exists, updating dependencies...
)

REM Install dependencies
echo Installing dependencies...
call venv\Scripts\activate.bat
pip install -r requirements.txt
echo.
echo ============================================
echo  Installation complete!
echo  Run "Start SQL Anonymizer.bat" to launch.
echo ============================================
pause
