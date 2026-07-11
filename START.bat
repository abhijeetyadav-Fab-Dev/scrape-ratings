@echo off
setlocal EnableDelayedExpansion
title RatingsScraper
cd /d "%~dp0"

:: ── First time? Run full installer ────────────────────────────────────
if not exist "%~dp0.setup_complete" (
    echo  [!] Setup not complete. Launching installer...
    call "%~dp0INSTALL_AND_RUN.bat"
    exit /b
)

:: ── Load saved python path ─────────────────────────────────────────────
set "PYTHONW_EXE="
if exist "%~dp0.python_path" (
    for /f "tokens=2 delims==" %%a in ('findstr "PYTHONW_EXE" "%~dp0.python_path"') do set "PYTHONW_EXE=%%a"
)

:: ── Verify python executable exists ────────────────────────────────────
if not defined PYTHONW_EXE goto :detect
if not exist "!PYTHONW_EXE!" goto :detect
goto :launch

:detect
echo  [!] Valid Python executable not found. Running system check...
del "%~dp0.setup_complete" >nul 2>nul
call "%~dp0INSTALL_AND_RUN.bat"
exit /b

:launch
start "" "!PYTHONW_EXE!" "%~dp0app.py"
exit /b 0
