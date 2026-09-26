@echo off
rem ---------------------------------------------------------------------------
rem  Starts the Nyx engine in the background at logon (the "NyxIchosEngine"
rem  scheduled task points here).
rem
rem  This used to run dist\Nyx\Nyx.exe. Windows Smart App Control blocks that
rem  unsigned executable (CodeIntegrity event 3077, task result 4551), so the
rem  engine never actually started. Python's own pythonw.exe is signed and
rem  allowed, and the launcher refuses to start a second copy, so this is also
rem  harmless when start-with-Windows is switched on as well.
rem ---------------------------------------------------------------------------
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" "%~dp0launcher.py" --background
)
