@echo off
rem Double-click to build what is missing and open the dashboard.
cd /d "%~dp0"
python run.py %*
rem Keep the window open if something went wrong, so the message can be read.
if errorlevel 1 pause
