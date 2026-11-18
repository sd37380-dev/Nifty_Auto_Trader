@echo off
title Dhan Broker Data Fetcher
cd /d "%~dp0"

echo ============================================================
echo         NIFTY Autonomous Trader - Broker Data Fetcher       
echo ============================================================
echo.
echo Connecting to Dhan HQ and fetching market candles + options...
echo.

if exist venv\Scripts\python.exe (
    venv\Scripts\python.exe scripts\fetch_broker_data.py --symbol NIFTY --interval 15 --days 60 --include-options
) else (
    python scripts\fetch_broker_data.py --symbol NIFTY --interval 15 --days 60 --include-options
)

echo.
pause
