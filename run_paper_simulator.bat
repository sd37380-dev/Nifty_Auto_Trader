@echo off
title NIFTY Option Paper Trade Simulator
cd /d "%~dp0"

:MENU
cls
echo ==============================================================================
echo          NIFTY OPTION PAPER TRADE SIMULATOR (100%% LOCAL, NO LLM)
echo ==============================================================================
echo Real market feeling: Traded Option Premiums, Slippage, Trailing SL,
echo Taxes, STT, GST, Exchange charges, and Zerodha/Dhan Brokerage.
echo ==============================================================================
echo.
echo [1] Run Backtest with My Custom Rule (user_rule.py)
echo [2] Run Live Candle-by-Candle Playback Animation (My Custom Rule)
echo [3] Run Backtest with Proven EMA14 + CPR Pivot Bounce Rule
echo [4] Run Backtest with Supertrend + RSI Momentum Rule
echo [5] Edit My Custom Rules (user_rule.py in Notepad)
echo [6] Exit
echo.
set /p opt="Select an option [1-6]: "

if "%opt%"=="1" goto RUN_CUSTOM_BACKTEST
if "%opt%"=="2" goto RUN_PLAYBACK
if "%opt%"=="3" goto RUN_EMA_PIVOT
if "%opt%"=="4" goto RUN_SUPERTREND
if "%opt%"=="5" goto EDIT_RULE
if "%opt%"=="6" goto EXIT

echo Invalid selection. Please try again.
pause
goto MENU

:RUN_CUSTOM_BACKTEST
cls
echo Running 30-day Fast Backtest with your custom rules from user_rule.py...
echo.
call venv\Scripts\activate.bat
venv\Scripts\python.exe -m nifty_trader.cli paper-simulator --rule custom --days 30
echo.
pause
goto MENU

:RUN_PLAYBACK
cls
echo Starting Live Candle Playback Simulation...
echo (Watch trades trigger candle-by-candle with real-time MTM and slippage)
echo.
call venv\Scripts\activate.bat
venv\Scripts\python.exe -m nifty_trader.cli paper-simulator --rule custom --days 10 --playback --speed 0.04
echo.
pause
goto MENU

:RUN_EMA_PIVOT
cls
echo Running Backtest with Proven EMA14 + CPR Pivot Bounce Rule...
echo.
call venv\Scripts\activate.bat
venv\Scripts\python.exe -m nifty_trader.cli paper-simulator --rule ema-pivot --days 30
echo.
pause
goto MENU

:RUN_SUPERTREND
cls
echo Running Backtest with Supertrend + RSI Momentum Rule...
echo.
call venv\Scripts\activate.bat
venv\Scripts\python.exe -m nifty_trader.cli paper-simulator --rule supertrend --days 30
echo.
pause
goto MENU

:EDIT_RULE
cls
echo Opening nifty_trader\simulator\user_rule.py for editing...
start notepad.exe nifty_trader\simulator\user_rule.py
goto MENU

:EXIT
exit
