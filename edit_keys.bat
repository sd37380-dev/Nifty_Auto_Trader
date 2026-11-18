@echo off
title Edit Broker & AI Keys
cd /d "%~dp0"
echo ==============================================================================
echo NIFTY Autonomous Trader - Secure Credential Configuration
echo ==============================================================================
echo Opening .env in Notepad...
echo.
echo Look for these lines at the bottom of the file:
echo   DHAN_CLIENT_ID=YOUR_DHAN_CLIENT_ID_HERE
echo   DHAN_ACCESS_TOKEN=YOUR_DHAN_ACCESS_TOKEN_HERE
echo.
echo Replace them with your actual Dhan HQ Client ID and Access Token.
echo When finished, press Ctrl+S to save, then close Notepad.
echo ==============================================================================
notepad .env
echo Done. Your keys are saved safely on your local computer.
pause
