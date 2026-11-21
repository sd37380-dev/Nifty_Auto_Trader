@echo off
title Hermes Quantitative Gap Market Strategy Engine
color 0B
cd /d "%~dp0"

echo ======================================================================
echo           HERMES QUANTITATIVE GAP TRADING ENGINE (NIFTY / BANKNIFTY)
echo ======================================================================
echo.
echo Select Mode:
echo   [1] Analyze Today's Gap Action (NIFTY 50)
echo   [2] Analyze Today's Gap Action (BANKNIFTY)
echo   [3] Run Live Autonomous Gap Trader (NIFTY - 09:15 to 10:30 Window)
echo   [4] Run Live Autonomous Gap Trader (BANKNIFTY - 09:15 to 10:30 Window)
echo   [5] Exit
echo.
set /p opt="Enter option [1-5]: "

if "%opt%"=="1" (
    echo.
    echo Analyzing NIFTY 50 Gap Structure...
    venv\Scripts\python.exe scripts\gap_market_strategy.py --symbol NIFTY --mode analyze
    pause
    exit /b
)
if "%opt%"=="2" (
    echo.
    echo Analyzing BANKNIFTY Gap Structure...
    venv\Scripts\python.exe scripts\gap_market_strategy.py --symbol BANKNIFTY --mode analyze
    pause
    exit /b
)
if "%opt%"=="3" (
    echo.
    echo Launching NIFTY Autonomous Gap Strategy Runner...
    venv\Scripts\python.exe scripts\gap_market_strategy.py --symbol NIFTY --mode live
    pause
    exit /b
)
if "%opt%"=="4" (
    echo.
    echo Launching BANKNIFTY Autonomous Gap Strategy Runner...
    venv\Scripts\python.exe scripts\gap_market_strategy.py --symbol BANKNIFTY --mode live
    pause
    exit /b
)
exit /b
