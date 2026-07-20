@echo off
cd /d "%~dp0"

:: 优先用 venv 的 Python
set PYTHON=python
if exist venv\Scripts\python.exe (
    set PYTHON=venv\Scripts\python.exe
)

%PYTHON% start.py
if %errorlevel% neq 0 (
    echo.
    echo If Python is not installed, download from:
    echo https://www.python.org/downloads/
    echo.
    pause
)
