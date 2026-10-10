@echo off
REM Double-click after the RSI launcher finishes patching LIVE.
REM Extracts the new stock global.ini, builds locally, and pushes an update branch to GitHub.
REM For PTU run:  update.bat PTU
setlocal
set CHANNEL=%1
if "%CHANNEL%"=="" set CHANNEL=LIVE
cd /d "%~dp0"
python -m pip install --quiet --disable-pip-version-check -r requirements.txt
python scripts\update_stock.py --channel %CHANNEL% --push
pause
