@echo off
setlocal EnableDelayedExpansion
title RatingsScraper - Setup and Launch
color 0A
cd /d "%~dp0"

echo.
echo  ==========================================
echo    RatingsScraper - First Time Setup
echo  ==========================================
echo.

:: ── Step 1: Check for Python ───────────────────────────────────────────
echo  [1/4] Checking for Python...
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo.
    echo  [!] Python not found. Downloading Python 3.11...
    echo.
    powershell -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe' -OutFile '$env:TEMP\python_installer.exe'"
    if !errorlevel! neq 0 (
        echo  [ERROR] Could not download Python. Please install from https://python.org
        pause
        exit /b 1
    )
    echo  [*] Installing Python 3.11...
    "%TEMP%\python_installer.exe" /quiet InstallAllUsers=0 PrependPath=1 Include_pip=1
    if !errorlevel! neq 0 (
        echo  [ERROR] Python install failed. Install manually from https://python.org
        pause
        exit /b 1
    )
    :: Refresh PATH
    for /f "skip=2 tokens=3*" %%a in ('reg query "HKCU\Environment" /v PATH 2^>nul') do set "UPATH=%%a %%b"
    set "PATH=%PATH%;%UPATH%"
)

:: ── Resolve exact python.exe and pythonw.exe paths ────────────────────
for /f "tokens=*" %%i in ('where python') do (
    set "PYTHON_EXE=%%i"
    goto :found_python
)
:found_python
:: Prefer Python311 if multiple are found
echo %PYTHON_EXE% | findstr /i "Python311" >nul 2>nul
if %errorlevel% neq 0 (
    :: Try to find Python311 explicitly
    if exist "C:\Users\%USERNAME%\AppData\Local\Programs\Python\Python311\python.exe" (
        set "PYTHON_EXE=C:\Users\%USERNAME%\AppData\Local\Programs\Python\Python311\python.exe"
    )
)

:: Derive pythonw path from python path
set "PYTHON_DIR=%PYTHON_EXE:~0,-10%"
set "PYTHONW_EXE=%PYTHON_DIR%pythonw.exe"

:: Fallback: if pythonw doesn't exist, just use python
if not exist "!PYTHONW_EXE!" (
    set "PYTHONW_EXE=!PYTHON_EXE!"
)

:: Save the paths for START.bat to reuse
echo PYTHON_EXE=!PYTHON_EXE! > "%~dp0.python_path"
echo PYTHONW_EXE=!PYTHONW_EXE! >> "%~dp0.python_path"

!PYTHON_EXE! --version > "%TEMP%\_pyver.txt" 2>nul
set /p PYVER=<"%TEMP%\_pyver.txt"
echo  [OK] Found !PYVER!
echo  [OK] Using: !PYTHON_EXE!

:: ── Step 2: Upgrade pip ────────────────────────────────────────────────
echo.
echo  [2/4] Upgrading pip...
"!PYTHON_EXE!" -m pip install --upgrade pip --quiet --no-warn-script-location

:: ── Step 3: Install packages ───────────────────────────────────────────
echo.
echo  [3/4] Installing required packages...
echo        (First run only - please wait ~1-2 min)
echo.
"!PYTHON_EXE!" -m pip install -r "%~dp0requirements.txt" --quiet --no-warn-script-location
if !errorlevel! neq 0 (
    echo  [!] Retry without version pins...
    "!PYTHON_EXE!" -m pip install PyQt6 playwright httpx pandas beautifulsoup4 lxml aiofiles openpyxl --quiet --no-warn-script-location
)
echo  [OK] Packages installed!

:: ── Step 4: Install Playwright Chromium ───────────────────────────────
echo.
echo  [4/4] Setting up browser engine (Chromium)...
echo        (One-time ~150MB download - please wait)
echo.
"!PYTHON_EXE!" -m playwright install chromium
if !errorlevel! neq 0 (
    "!PYTHON_EXE!" -m playwright install chromium --force
)
echo  [OK] Browser engine ready!

:: ── Mark setup complete ────────────────────────────────────────────────
echo SETUP_DONE=1 > "%~dp0.setup_complete"
echo %date% %time% >> "%~dp0.setup_complete"

:: ── Launch app ─────────────────────────────────────────────────────────
echo.
echo  ==========================================
echo    All Done! Launching RatingsScraper...
echo  ==========================================
echo.
ping -n 3 127.0.0.1 >nul
start "" "!PYTHONW_EXE!" "%~dp0app.py"
exit /b 0
