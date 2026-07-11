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

:: ── Step 1: Check for Python or Setup Portable Python ───────────────────
echo  [1/4] Checking for Python environment...

set "PYTHON_EXE="
set "PYTHONW_EXE="

:: 1. Check if we already have a portable python embed environment
if exist "%~dp0python_embed\python.exe" (
    set "PYTHON_EXE=%~dp0python_embed\python.exe"
    set "PYTHONW_EXE=%~dp0python_embed\pythonw.exe"
    echo  [*] Found local portable Python environment.
    goto :python_resolved
)

:: 2. Check if global python exists
where python >nul 2>nul
if %errorlevel% eq 0 (
    for /f "tokens=*" %%i in ('where python') do (
        set "GLOBAL_PY=%%i"
        goto :check_global
    )
    :check_global
    :: Prefer Python311/Python312 if multiple are found
    if exist "C:\Users\%USERNAME%\AppData\Local\Programs\Python\Python311\python.exe" (
        set "PYTHON_EXE=C:\Users\%USERNAME%\AppData\Local\Programs\Python\Python311\python.exe"
    ) else if exist "C:\Users\%USERNAME%\AppData\Local\Programs\Python\Python312\python.exe" (
        set "PYTHON_EXE=C:\Users\%USERNAME%\AppData\Local\Programs\Python\Python312\python.exe"
    ) else (
        set "PYTHON_EXE=!GLOBAL_PY!"
    )
    
    :: Derive pythonw path
    set "PYTHON_DIR=!PYTHON_EXE:~0,-10!"
    set "PYTHONW_EXE=!PYTHON_DIR!pythonw.exe"
    if not exist "!PYTHONW_EXE!" set "PYTHONW_EXE=!PYTHON_EXE!"
    
    echo  [OK] Found global Python installation: !PYTHON_EXE!
    goto :python_resolved
)

:: 3. If Python is not found, download and setup Portable Python 3.11
echo.
echo  [!] No Python installation detected on your system.
echo  [*] Downloading Portable Python 3.11.9 (embeddable)...
echo      (This is lightweight ~10MB and runs self-contained - no admin required)
echo.

if not exist "%~dp0python_embed" mkdir "%~dp0python_embed"

powershell -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip' -OutFile '%~dp0python_embed.zip'"
if !errorlevel! neq 0 (
    echo  [ERROR] Could not download Python embed package. Please check your internet connection.
    pause
    exit /b 1
)

echo  [*] Extracting Portable Python environment...
powershell -Command "Expand-Archive -Path '%~dp0python_embed.zip' -DestinationPath '%~dp0python_embed' -Force"
del "%~dp0python_embed.zip" >nul 2>nul

echo  [*] Installing pip package manager...
powershell -Command "Invoke-WebRequest -Uri 'https://bootstrap.pypa.io/get-pip.py' -OutFile '%~dp0python_embed\get-pip.py'"
"%~dp0python_embed\python.exe" "%~dp0python_embed\get-pip.py" --no-warn-script-location
del "%~dp0python_embed\get-pip.py" >nul 2>nul

echo  [*] Configuring path references...
powershell -Command "Get-ChildItem '%~dp0python_embed' -Filter '*._pth' | ForEach-Object { (Get-Content $_.FullName) -replace '#import site', 'import site' | Set-Content $_.FullName }"

set "PYTHON_EXE=%~dp0python_embed\python.exe"
set "PYTHONW_EXE=%~dp0python_embed\pythonw.exe"
echo  [OK] Portable Python environment configured!

:python_resolved
:: Save resolved paths
echo PYTHON_EXE=!PYTHON_EXE!> "%~dp0.python_path"
echo PYTHONW_EXE=!PYTHONW_EXE!>> "%~dp0.python_path"

!PYTHON_EXE! --version > "%TEMP%\_pyver.txt" 2>nul
set /p PYVER=<"%TEMP%\_pyver.txt"
echo  [OK] Version: !PYVER!

:: ── Step 2: Upgrade pip ────────────────────────────────────────────────
echo.
echo  [2/4] Upgrading pip...
"!PYTHON_EXE!" -m pip install --upgrade pip --quiet --no-warn-script-location

:: ── Step 3: Install packages ───────────────────────────────────────────
echo.
echo  [3/4] Installing required packages...
echo        (This runs once - please wait ~1-2 min)
echo.
"!PYTHON_EXE!" -m pip install -r "%~dp0requirements.txt" --quiet --no-warn-script-location
if !errorlevel! neq 0 (
    echo  [!] Retry installing without version pins...
    "!PYTHON_EXE!" -m pip install PyQt6 playwright httpx pandas beautifulsoup4 lxml aiofiles openpyxl --quiet --no-warn-script-location
)
echo  [OK] Python dependencies installed!

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
