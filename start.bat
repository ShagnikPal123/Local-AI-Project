@echo off
setlocal enabledelayedexpansion
title Nyx Ichos
cd /d "%~dp0"

echo.
echo   ===================================================
echo   Nyx Ichos - Local-First AI Assistant
echo   Created by Shagnik
echo   ===================================================
echo.

REM --- 1. Python Environment Check ------------------------------------------
set "PY="
if exist ".venv\Scripts\python.exe" (
    set "PY=.venv\Scripts\python.exe"
    echo   [1/4] Using active virtual environment.
) else (
    echo   [1/4] Virtual environment not found. Running setup...
    where py >nul 2>&1
    if !errorlevel! equ 0 (
        set "BOOTSTRAP=py"
    ) else (
        where python >nul 2>&1
        if !errorlevel! equ 0 (
            set "BOOTSTRAP=python"
        ) else (
            echo.
            echo   ERROR: Python is not installed or not in your PATH.
            echo   Download and install Python 3.10+ from https://www.python.org/
            echo.
            pause
            exit /b 1
        )
    )
    !BOOTSTRAP! -m venv .venv
    set "PY=.venv\Scripts\python.exe"
)

REM --- 2. Dependencies Check ------------------------------------------------
"%PY%" -c "import fastapi" >nul 2>&1
if !errorlevel! neq 0 (
    echo   [2/4] Installing required packages...
    "%PY%" -m pip install --quiet --upgrade pip
    "%PY%" -m pip install --quiet -r requirements.txt
) else (
    echo   [2/4] Dependencies verified.
)

REM --- 3. Frontend Check ----------------------------------------------------
if exist "frontend\nyx-pulse\dist\app\index.html" (
    echo   [3/4] Workspace UI is ready.
) else (
    where npm >nul 2>&1
    if !errorlevel! equ 0 (
        echo   [3/4] Building Workspace UI bundle...
        pushd frontend\nyx-pulse
        call npm install --silent
        call npm run build --silent
        popd
    ) else (
        echo   [3/4] Notice: Node.js npm not detected. Using existing or terminal mode.
    )
)

REM --- 4. Launch ------------------------------------------------------------
echo   [4/4] Starting Nyx Engine on http://localhost:8000 ...
echo.
echo   Press Ctrl+C to stop the engine.
echo.

start "" /b cmd /c "timeout /t 2 /nobreak >nul & start http://localhost:8000/"

"%PY%" -m uvicorn server:app --host 127.0.0.1 --port 8000

pause
