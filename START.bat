@echo off
setlocal EnableDelayedExpansion
title RatingsScraper
cd /d "%~dp0"

:: ── First time? Run full installer ────────────────────────────────────
if not exist "%~dp0.setup_complete" (
    echo  [!] First time detected - running setup...
    call "%~dp0INSTALL_AND_RUN.bat"
    exit /b
)

:: ── Load saved python path ─────────────────────────────────────────────
set "PYTHONW_EXE="
if exist "%~dp0.python_path" (
    for /f "tokens=2 delims==" %%a in ('findstr "PYTHONW_EXE" "%~dp0.python_path"') do set "PYTHONW_EXE=%%a"
)

:: ── Fallback: detect pythonw on the fly ───────────────────────────────
if not defined PYTHONW_EXE goto :detect
if not exist "!PYTHONW_EXE!" goto :detect
goto :launch

:detect
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo  [!] Python not found - re-running setup...
    del "%~dp0.setup_complete" >nul 2>nul
    call "%~dp0INSTALL_AND_RUN.bat"
    exit /b
)
:: Prefer Python311
if exist "C:\Users\%USERNAME%\AppData\Local\Programs\Python\Python311\pythonw.exe" (
    set "PYTHONW_EXE=C:\Users\%USERNAME%\AppData\Local\Programs\Python\Python311\pythonw.exe"
    goto :launch
)
for /f "tokens=*" %%i in ('where python') do (
    set "PYTHON_EXE=%%i"
    goto :found
)
:found
set "PYTHON_DIR=!PYTHON_EXE:~0,-10!"
set "PYTHONW_EXE=!PYTHON_DIR!pythonw.exe"
if not exist "!PYTHONW_EXE!" set "PYTHONW_EXE=!PYTHON_EXE!"

:launch
start "" "!PYTHONW_EXE!" "%~dp0app.py"
exit /b 0
