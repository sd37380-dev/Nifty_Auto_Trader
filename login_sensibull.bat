@echo off
title NIFTY Autonomous Trader - Sensibull Browser Login
cd /d "%~dp0"
echo ==============================================================================
echo Opening Chrome for Sensibull login...
echo 1. Sign in to Sensibull using Google or your broker.
echo 2. Once logged in, close the browser window.
echo Your session will be saved automatically for paper trading.
echo ==============================================================================
echo.
call venv\Scripts\activate.bat
venv\Scripts\python.exe -m nifty_trader.cli browser-login
echo.
echo Browser login session closed.
pause
