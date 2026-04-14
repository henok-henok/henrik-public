@echo off
echo Starting SQL Anonymizer...

REM Check venv exists
if not exist "venv\Scripts\activate.bat" (
    echo ERROR: Virtual environment not found.
    echo Please run Install.bat first.
    pause
    exit /b 1
)

REM Activate venv and run
call venv\Scripts\activate.bat
streamlit run app.py
