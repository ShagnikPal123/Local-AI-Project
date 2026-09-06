@echo off
REM Quick launcher for Nyx Pulse - run from command line
REM Usage: chat "your question"
REM        chat --attribute coding "your question"
REM        chat (for interactive mode)

cd /d "%~dp0"
python cli.py %*
pause
