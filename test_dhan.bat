@echo off
title Test Dhan HQ Broker Live Data Connection
cd /d "%~dp0"
echo ==============================================================================
echo Testing Dhan HQ Broker Data Connection...
echo ==============================================================================
echo.
call venv\Scripts\activate.bat
venv\Scripts\python.exe scripts/test_dhan_connection.py
echo.
pause
