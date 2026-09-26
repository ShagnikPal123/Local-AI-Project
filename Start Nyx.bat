@echo off
setlocal EnableExtensions EnableDelayedExpansion
title Nyx Ichos
cd /d "%~dp0"

rem ===========================================================================
rem  Start Nyx - double-click this. That is the whole instruction.
rem
rem  First run (a couple of minutes, once): finds Python or installs it for this
rem  user, installs Nyx's packages, creates the "Nyx Ichos" desktop shortcut,
rem  registers the nyx:// start link, turns on start-with-Windows, starts Nyx.
rem
rem  Every run after that: starts Nyx in the background (tray icon near the
rem  clock) and opens it in your browser, then this window closes itself.
rem
rem  Why Python's pythonw.exe and not an .exe of our own: Windows Smart App
rem  Control blocks unsigned programs it has never seen, which is exactly what
rem  a home-built Nyx.exe is. Python's interpreter is signed and allowed.
rem ===========================================================================

if /i "%~1"=="--repair" (
    if exist ".venv\nyx-ready.txt" del ".venv\nyx-ready.txt" >nul 2>&1
    shift
)

rem ---- Already set up: start quietly and get out of the way -----------------
if exist ".venv\Scripts\pythonw.exe" if exist ".venv\nyx-ready.txt" (
    start "" ".venv\Scripts\pythonw.exe" "%~dp0launcher.py" %1 %2 %3
    exit /b 0
)

echo.
echo   Nyx Ichos - first-time setup
echo   ---------------------------------------------------------------
echo   This happens once and takes a couple of minutes.
echo.

rem ---- 1. A Python interpreter (3.11 or newer) ------------------------------
set "PY="
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -c "import sys" >nul 2>&1 && set PY=".venv\Scripts\python.exe"
)
if not defined PY call :find_python

if not defined PY (
    echo   [1/3] Python is not installed. Installing it for you ^(no admin needed^)...
    where winget >nul 2>&1
    if errorlevel 1 (
        echo.
        echo   Could not install Python automatically ^(winget is missing^).
        echo   Install Python from https://www.python.org/downloads/ and then
        echo   double-click Start Nyx again.
        start "" "https://www.python.org/downloads/windows/"
        pause
        exit /b 1
    )
    winget install --id Python.Python.3.13 --exact --scope user --silent --accept-package-agreements --accept-source-agreements
    call :find_python
)

if not defined PY (
    echo.
    echo   Python was installed but this window cannot see it yet.
    echo   Close this window and double-click Start Nyx again.
    pause
    exit /b 1
)
echo   [1/3] Python: ready.

rem ---- 2. Nyx's private environment and packages ----------------------------
if not exist ".venv\Scripts\python.exe" (
    echo   [2/3] Creating Nyx's private Python environment...
    !PY! -m venv .venv
    if errorlevel 1 goto :fail
)
echo   [2/3] Installing Nyx's packages ^(first run downloads about 80 MB^)...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check --quiet --upgrade pip
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto :fail

rem ---- 3. Shortcut, nyx:// link, start with Windows, launch -----------------
echo   [3/3] Creating the desktop shortcut and starting Nyx...
".venv\Scripts\python.exe" "%~dp0setup_nyx.py"
if errorlevel 1 goto :fail

echo.
echo   All set. Nyx is starting - look for its icon near the clock.
echo   Next time, just double-click "Nyx Ichos" on your desktop.
timeout /t 6 >nul
exit /b 0

:find_python
for %%V in (3.14 3.13 3.12 3.11) do (
    if not defined PY (
        py -%%V -c "import sys" >nul 2>&1 && set "PY=py -%%V"
    )
)
if not defined PY (
    for %%P in (
        "%LOCALAPPDATA%\Programs\Python\Python314\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
        "%LOCALAPPDATA%\Python\pythoncore-3.14-64\python.exe"
        "%LOCALAPPDATA%\Python\pythoncore-3.13-64\python.exe"
        "%ProgramFiles%\Python314\python.exe"
        "%ProgramFiles%\Python313\python.exe"
    ) do (
        if not defined PY if exist %%P set PY="%%~P"
    )
)
if not defined PY (
    rem A bare "python" may be the Microsoft Store stub, which prints an install
    rem hint and fails; the version check below rejects it.
    python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1 && set "PY=python"
)
exit /b 0

:fail
echo.
echo   Setup did not finish. The first error is above this line.
echo   Fix it (usually the internet connection) and double-click Start Nyx again.
pause
exit /b 1
