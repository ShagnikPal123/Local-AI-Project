@echo off
rem Ichos Trader, one click. The first run installs what it needs (a minute or two);
rem every run starts the trader in a small window and opens the dashboard.
rem Closing that window stops the trader. Extra options pass through, e.g. --offline.
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" goto run

echo Setting up Ichos Trader, first run only...
py -3 -m venv .venv >nul 2>&1
if not exist ".venv\Scripts\python.exe" python -m venv .venv >nul 2>&1
if not exist ".venv\Scripts\python.exe" goto nopython
".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed

:run
start "Ichos Trader" /min ".venv\Scripts\python.exe" run_trader.py --forever --open %*
exit /b 0

:nopython
echo.
echo Ichos Trader needs Python 3.11 or newer. Opening the download page:
echo install it, tick "Add python.exe to PATH", then double-click this file again.
start "" https://www.python.org/downloads/
pause
exit /b 1

:failed
echo.
echo The install did not finish. Check the internet connection and double-click this file again.
pause
exit /b 1
