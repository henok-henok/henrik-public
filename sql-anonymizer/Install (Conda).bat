@echo off
pushd "%~dp0"

echo ============================================
echo  SQL Anonymizer - Conda Setup
echo ============================================
echo.

REM Check if conda is already on PATH
where conda >nul 2>nul
if errorlevel 1 (
    REM Try default Anaconda/Miniconda install locations
    if exist "%USERPROFILE%\Anaconda3\condabin\activate.bat" (
        echo Conda not on PATH. Activating from Anaconda3...
        CALL "%USERPROFILE%\Anaconda3\condabin\activate.bat"
    ) else if exist "%USERPROFILE%\Miniconda3\condabin\activate.bat" (
        echo Conda not on PATH. Activating from Miniconda3...
        CALL "%USERPROFILE%\Miniconda3\condabin\activate.bat"
    )
)

REM Verify conda is now available
where conda >nul 2>nul
if errorlevel 1 (
    echo ERROR: conda not found.
    echo Install Anaconda or Miniconda first.
    echo https://docs.anaconda.com/anaconda/install/
    echo.
    popd
    pause
    exit /b 1
)

REM Check if environment already exists
conda info --envs | findstr /C:"sql_anonymizer" >nul 2>nul
if not errorlevel 1 (
    echo Environment 'sql_anonymizer' already exists.
    echo Updating from environment.yml...
    echo.
    call conda env update -f environment.yml --prune
) else (
    echo Creating environment 'sql_anonymizer'...
    echo.
    call conda env create -f environment.yml
)

echo.
echo ============================================
echo  Done. Use 'Start SQL Anonymizer (Conda).bat'
echo  to launch the app.
echo ============================================
popd
pause
