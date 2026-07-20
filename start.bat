@echo off
cd /d "%~dp0"

:: 检查 venv 是否存在且 playwright 已装好
set VENV_PY=venv\Scripts\python.exe
if exist %VENV_PY% (
    %VENV_PY% -c "import playwright" 2>nul
    if errorlevel 1 (
        echo [..] Playwright 未安装，运行 setup.bat...
        call setup.bat
        if errorlevel 1 (
            echo [错误] 环境搭建失败，请检查网络后重试
            pause
            exit /b 1
        )
    )
    %VENV_PY% web_gui.py
) else (
    echo [..] venv 不存在，运行 setup.bat...
    call setup.bat
    if errorlevel 1 (
        echo [错误] 环境搭建失败
        pause
        exit /b 1
    )
    venv\Scripts\python.exe web_gui.py
)

if errorlevel 1 (
    echo.
    echo If Python is not installed, download from:
    echo https://www.python.org/downloads/
    echo.
    pause
)
