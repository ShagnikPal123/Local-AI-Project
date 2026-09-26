@echo off
REM Quick launcher for the Nyx terminal chat.
REM Usage: chat "your question"
REM        chat --attribute coding "your question"
REM        chat (for interactive mode)
REM
REM A bare "python" is the Microsoft Store stub on many PCs and has none of
REM Nyx's packages, so always use the project environment.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" call "%~dp0Start Nyx.bat" --repair
".venv\Scripts\python.exe" cli.py %*
pause
