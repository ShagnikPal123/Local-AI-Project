@echo off
rem Re-runs the one-time setup: packages, desktop shortcut, nyx:// link and
rem start-with-Windows. Safe to run any time; it repairs whatever is missing.
call "%~dp0Start Nyx.bat" --repair
