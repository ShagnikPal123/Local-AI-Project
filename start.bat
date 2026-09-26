@echo off
rem Kept so old shortcuts and habits still work. Everything now goes through
rem "Start Nyx.bat", which sets Nyx up on first run and starts it in the
rem background (tray icon) every time after.
call "%~dp0Start Nyx.bat" %*
