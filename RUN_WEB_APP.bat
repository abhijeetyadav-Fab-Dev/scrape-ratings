@echo off
setlocal EnableDelayedExpansion
title ScrapeRatings Web App Launcher
cd /d "%~dp0"

echo  ==========================================
echo    ScrapeRatings - Launching Web Dashboard
echo  ==========================================
echo.

:: ── Step 1: Detect Python ──────────────────────────────────────────────
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo  [!] Python not found. Please run INSTALL_AND_RUN.bat first to set up the environment.
    pause
    exit /b 1
)

:: Find pythonw.exe or python.exe
for /f "tokens=*" %%i in ('where python') do (
    set "PYTHON_EXE=%%i"
    goto :found_python
)
:found_python

set "PYTHON_DIR=!PYTHON_EXE:~0,-10!"
set "PYTHONW_EXE=!PYTHON_DIR!pythonw.exe"
if not exist "!PYTHONW_EXE!" set "PYTHONW_EXE=!PYTHON_EXE!"

:: ── Step 2: Open Browser to local dashboard ───────────────────────────
echo  [*] Opening web dashboard in your browser...
start "" "http://127.0.0.1:5000"

:: ── Step 3: Run Flask server ──────────────────────────────────────────
echo  [*] Starting Flask server on http://127.0.0.1:5000...
echo  [*] Press Ctrl+C in this window to stop the server.
echo.
"!PYTHON_EXE!" "%~dp0web_app\app.py"

pause
