@echo off
title NIFTY Autonomous Trader - Trade Audit Log
cd /d "%~dp0"
echo ==============================================================================
echo Displaying Trade Audit Records & Attribution by Mode
echo ==============================================================================
echo.
call venv\Scripts\activate.bat
venv\Scripts\python.exe -m nifty_trader.cli trades --mode all
echo.
pause
