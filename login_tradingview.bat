@echo off
title NIFTY Autonomous Trader - TradingView Browser Login
cd /d "%~dp0"
echo ==============================================================================
echo Opening Chrome for TradingView login and chart setup...
echo 1. Sign in to your TradingView account so your charts and indicators load.
echo 2. Open your NIFTY chart and customize it as you prefer.
echo 3. Once set, close the browser window.
echo Your login session and chart layout will be saved in data/browser/chrome_profile.
echo ==============================================================================
echo.
call venv\Scripts\activate.bat
venv\Scripts\python.exe -m nifty_trader.cli browser-login --target tradingview
echo.
echo TradingView session saved.
pause
