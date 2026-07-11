@echo off
setlocal EnableDelayedExpansion
title ScrapeRatings Web App Launcher
cd /d "%~dp0"

echo  ==========================================
echo    ScrapeRatings - Launching Web Dashboard
echo  ==========================================
echo.

:: ── Step 1: Resolve Python path from .python_path if exists ──────────────
set "PYTHON_EXE="
if exist "%~dp0.python_path" (
    for /f "tokens=2 delims==" %%a in ('findstr "PYTHON_EXE" "%~dp0.python_path"') do set "PYTHON_EXE=%%a"
)

if not defined PYTHON_EXE (
    where python >nul 2>nul
    if !errorlevel! eq 0 (
        set "PYTHON_EXE=python"
    ) else (
        echo [!] Environment not set up. Please run START.bat or INSTALL_AND_RUN.bat first.
        pause
        exit /b 1
    )
)

if not exist "!PYTHON_EXE!" (
    where python >nul 2>nul
    if !errorlevel! eq 0 (
        set "PYTHON_EXE=python"
    ) else (
        echo [!] Environment path invalid. Please run START.bat or INSTALL_AND_RUN.bat first.
        pause
        exit /b 1
    )
)

:: ── Step 2: Open Browser to local dashboard ───────────────────────────
echo  [*] Opening web dashboard in your browser...
start "" "http://127.0.0.1:5000"

:: ── Step 3: Run Flask server ──────────────────────────────────────────
echo  [*] Starting Flask server on http://127.0.0.1:5000...
echo  [*] Press Ctrl+C in this window to stop the server.
echo.
"!PYTHON_EXE!" "%~dp0web_app\app.py"

pause
