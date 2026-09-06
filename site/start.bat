@echo off
setlocal enabledelayedexpansion
title Nyx Ichos
cd /d "%~dp0"

echo.
echo   Nyx Ichos
echo   Local-first AI agent - created by Shagnik
echo   ---------------------------------------------------
echo.

REM --- 1. Python -------------------------------------------------------------
set "PY="
if exist ".venv\Scripts\python.exe" (
    set "PY=.venv\Scripts\python.exe"
    echo   [1/4] Using the existing environment.
) else (
    echo   [1/4] First run - creating the Python environment...

    where py >nul 2>&1
    if !errorlevel! equ 0 (
        set "BOOTSTRAP=py"
    ) else (
        where python >nul 2>&1
        if !errorlevel! equ 0 (
            set "BOOTSTRAP=python"
        ) else (
            echo.
            echo   PROBLEM: Python is not installed, or not on PATH.
            echo.
            echo   Install it from https://www.python.org/downloads/
            echo   and tick "Add Python to PATH" during setup. Then run this again.
            echo.
            pause
            exit /b 1
        )
    )

    !BOOTSTRAP! -m venv .venv
    if !errorlevel! neq 0 (
        echo.
        echo   PROBLEM: could not create the environment.
        echo   Try running this file as Administrator.
        echo.
        pause
        exit /b 1
    )
    set "PY=.venv\Scripts\python.exe"
)

REM --- 2. Dependencies -------------------------------------------------------
"%PY%" -c "import fastapi" >nul 2>&1
if !errorlevel! neq 0 (
    echo   [2/4] Installing dependencies - this takes a minute, once...
    "%PY%" -m pip install --quiet --upgrade pip
    "%PY%" -m pip install --quiet -r requirements.txt
    if !errorlevel! neq 0 (
        echo.
        echo   PROBLEM: dependencies failed to install.
        echo   Check your internet connection and run this again.
        echo.
        pause
        exit /b 1
    )
) else (
    echo   [2/4] Dependencies are already installed.
)

REM --- 3. The workspace UI ---------------------------------------------------
if exist "frontend\nyx-pulse\dist\app\index.html" (
    echo   [3/4] Workspace is already built.
) else (
    where npm >nul 2>&1
    if !errorlevel! equ 0 (
        echo   [3/4] Building the workspace - this takes a minute, once...
        pushd frontend\nyx-pulse
        call npm install --silent
        call npm run build --silent
        popd
    ) else (
        echo   [3/4] Node.js not found - skipping the browser workspace build.
        echo         The API and the terminal app (python cli.py) still work.
    )
)

REM --- 4. Launch -------------------------------------------------------------
echo   [4/4] Starting the engine...
echo.
echo   ---------------------------------------------------
echo   Opening http://localhost:8000 in your browser.
echo.
echo   Leave this window open while you use Nyx.
echo   Close it, or press Ctrl+C, to stop.
echo   ---------------------------------------------------
echo.

start "" /b cmd /c "timeout /t 3 /nobreak >nul & start http://localhost:8000"

"%PY%" -m uvicorn server:app --host 127.0.0.1 --port 8000

echo.
echo   Nyx has stopped.
pause
