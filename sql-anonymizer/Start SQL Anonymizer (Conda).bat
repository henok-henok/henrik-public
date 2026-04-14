@echo off
pushd "%~dp0"

REM Check if conda is already on PATH
where conda >nul 2>nul
if errorlevel 1 (
    REM Try default Anaconda/Miniconda install locations
    if exist "%USERPROFILE%\Anaconda3\condabin\activate.bat" (
        CALL "%USERPROFILE%\Anaconda3\condabin\activate.bat"
    ) else if exist "%USERPROFILE%\Miniconda3\condabin\activate.bat" (
        CALL "%USERPROFILE%\Miniconda3\condabin\activate.bat"
    )
)

REM Verify conda is now available
where conda >nul 2>nul
if errorlevel 1 (
    echo ERROR: conda not found.
    echo Run 'Install (Conda).bat' first.
    popd
    pause
    exit /b 1
)

call conda activate sql_anonymizer
if errorlevel 1 (
    echo ERROR: Environment 'sql_anonymizer' not found.
    echo Run 'Install (Conda).bat' first.
    popd
    pause
    exit /b 1
)

streamlit run app.py
popd
pause
