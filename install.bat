@echo off
setlocal enabledelayedexpansion
title Nyx Ichos Installer
cd /d "%~dp0"

echo.
echo   ===================================================
echo   Nyx Ichos - One-Click Local Installer
echo   Created by Shagnik
echo   ===================================================
echo.

REM --- 1. Python Check ---
set "BOOTSTRAP="
where py >nul 2>&1
if !errorlevel! equ 0 (
    set "BOOTSTRAP=py"
) else (
    where python >nul 2>&1
    if !errorlevel! equ 0 (
        set "BOOTSTRAP=python"
    ) else (
        echo   [!] Python not found. Please install Python 3.10+ from python.org
        echo       Make sure to check "Add Python to PATH".
        pause
        exit /b 1
    )
)

echo   [*] Setting up Python virtual environment (.venv)...
if not exist ".venv\Scripts\python.exe" (
    !BOOTSTRAP! -m venv .venv
)

set "PY=.venv\Scripts\python.exe"

echo   [*] Installing dependencies from requirements.txt...
"%PY%" -m pip install --quiet --upgrade pip
"%PY%" -m pip install --quiet -r requirements.txt

REM --- 2. Environment Setup ---
if not exist ".env.local" (
    if exist ".env.example" (
        copy .env.example .env.local >nul
        echo   [*] Created .env.local template. Add your API keys here anytime.
    )
)

REM --- 3. Build UI if needed ---
if not exist "frontend\nyx-pulse\dist\app\index.html" (
    where npm >nul 2>&1
    if !errorlevel! equ 0 (
        echo   [*] Compiling React Workspace UI...
        pushd frontend\nyx-pulse
        call npm install --silent
        call npm run build --silent
        popd
    )
)

REM --- 4. Create Desktop Shortcut ---
echo   [*] Creating Windows Desktop Shortcut...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$WshShell = New-Object -ComObject WScript.Shell; $Shortcut = $WshShell.CreateShortcut([Environment]::GetFolderPath('Desktop') + '\Nyx Ichos.lnk'); $Shortcut.TargetPath = '%~dp0start.bat'; $Shortcut.WorkingDirectory = '%~dp0'; $Shortcut.Description = 'Nyx Ichos Local AI Assistant'; if (Test-Path '%~dp0site\favicon.ico') { $Shortcut.IconLocation = '%~dp0site\favicon.ico' }; $Shortcut.Save()" 2>nul
if !errorlevel! equ 0 (
    echo   [+] Desktop Shortcut "Nyx Ichos" created!
)

echo.
echo   ===================================================
echo   Installation Complete!
echo   To launch Nyx, double-click start.bat or the Desktop shortcut.
echo   ===================================================
echo.
pause
