@echo off
REM ---------------------------------------------------------------------------
REM  Starts the Nyx engine in the background and keeps it running.
REM  Registered as the "NyxIchosEngine" scheduled task, which fires at logon.
REM
REM  NYX_DATA_DIR is set explicitly so the engine reads the .env.local, chats and
REM  memory that already live in this folder. Without it a packaged build stores
REM  state under %LOCALAPPDATA%, which would be a second, empty world with no API
REM  key in it - the engine would start fine and then be unable to answer
REM  anything, which is a confusing way to fail.
REM ---------------------------------------------------------------------------
cd /d "%~dp0"
set "NYX_DATA_DIR=%~dp0"
"%~dp0dist\Nyx\Nyx.exe" --no-browser --strict-port
