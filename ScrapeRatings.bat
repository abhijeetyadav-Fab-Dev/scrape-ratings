@echo off
setlocal EnableDelayedExpansion
title Hotel Ratings Scraper CLI
cd /d "%~dp0"

echo ==========================================
echo   Hotel Ratings Scraper (Command-Line)
echo ==========================================
echo.

if "%~1"=="" (
    set /p CSV_PATH="Drag and drop your CSV file here (or type path): "
) else (
    set CSV_PATH=%~1
)

:: Clean quotes from path
set CSV_PATH=!CSV_PATH:"=!

:: Resolve Python path from .python_path if exists
set "PYTHON_EXE="
if exist "%~dp0.python_path" (
    for /f "tokens=2 delims==" %%a in ('findstr "PYTHON_EXE" "%~dp0.python_path"') do set "PYTHON_EXE=%%a"
)

if not defined PYTHON_EXE (
    where python >nul 2>nul
    if !errorlevel! eq 0 (
        set "PYTHON_EXE=python"
    ) else (
        echo [!] Environment not set up. Running full installer first...
        call "%~dp0INSTALL_AND_RUN.bat"
        exit /b
    )
)

if not exist "!PYTHON_EXE!" (
    where python >nul 2>nul
    if !errorlevel! eq 0 (
        set "PYTHON_EXE=python"
    )
)

echo.
echo Scraping ratings from CSV: !CSV_PATH!
echo.
"!PYTHON_EXE!" "%~dp0scrape_ratings.py" "!CSV_PATH!"
echo.
pause
