@echo off
cd /d "%~dp0"

if exist venv\Scripts\python.exe (
    venv\Scripts\python.exe web_gui.py
) else (
    python web_gui.py
)

if errorlevel 1 (
    echo.
    echo If Python is not installed, download from:
    echo https://www.python.org/downloads/
    echo.
    pause
)
