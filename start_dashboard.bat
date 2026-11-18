@echo off
title NIFTY Autonomous Trader - Dashboard
cd /d "%~dp0"
echo ==============================================================================
echo Starting NIFTY Autonomous Trader Web Dashboard...
echo Local URL: http://127.0.0.1:8080
echo ==============================================================================
echo.
call venv\Scripts\activate.bat
venv\Scripts\python.exe -m nifty_trader.cli dashboard --port 8080
echo.
pause
