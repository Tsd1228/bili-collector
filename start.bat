@echo off
cd /d "%~dp0"
python start.py
if errorlevel 1 (
    echo.
    echo If Python is not installed, download from:
    echo https://www.python.org/downloads/
    echo.
    pause
)
