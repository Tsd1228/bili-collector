@echo off
title B站收藏夹数据分析项目 - 环境搭建
echo ==============================================
echo   BiliCollector - Environment Setup
echo ==============================================
echo.

:: ---------- 1. Check Python ----------
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found.
    echo   Download: https://www.python.org/downloads/
    echo   Make sure to check "Add Python to PATH" during install.
    echo.
    pause
    exit /b 1
)
python --version
echo.

:: ---------- 2. Create venv ----------
if exist venv\Scripts\python.exe (
    echo [INFO] venv already exists, skipping
) else (
    echo [..] Creating virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo [ERROR] Failed to create venv
        pause
        exit /b 1
    )
    echo [OK] venv created
)

:: ---------- 3. Install dependencies ----------
echo [..] Upgrading pip...
venv\Scripts\python.exe -m pip install --upgrade pip -q

echo [..] Installing Python packages...
venv\Scripts\pip.exe install -r requirements.txt -q
if errorlevel 1 (
    echo [ERROR] Package installation failed
    pause
    exit /b 1
)
echo [OK] Dependencies installed

:: ---------- 4. Install Playwright browsers ----------
echo [..] Installing Playwright browser (Chromium)...
venv\Scripts\python.exe -m playwright install chromium
echo [OK] Playwright browser ready

:: ---------- 5. Lock versions ----------
venv\Scripts\pip.exe freeze > requirements-locked.txt 2>nul
echo [OK] Versions locked to requirements-locked.txt

echo.
echo ==============================================
echo   Setup complete!
echo   Run: start.bat
echo ==============================================
pause
