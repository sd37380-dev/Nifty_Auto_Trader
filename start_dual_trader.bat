@echo off
title NIFTY Autonomous Trader - Dual Autonomous Modes
cd /d "%~dp0"
echo ==============================================================================
echo Launching Dual Autonomous Trader (Mode A + Mode B)
echo Mode A: Market Perception + Trading Brain
echo Mode B: Quantitative Data Research + Statistical Hypothesis Testing
echo ==============================================================================
echo.
call venv\Scripts\activate.bat
venv\Scripts\python.exe -m nifty_trader.cli autonomous start --mode dual --symbol NIFTY
echo.
echo Autonomous engine stopped.
pause
