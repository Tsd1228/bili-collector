@echo off
chcp 65001 >nul
title B站收藏夹数据分析项目 — 环境搭建
echo ==============================================
echo   B站收藏夹数据分析项目 — 环境搭建
echo ==============================================
echo.

:: 1. 找 Python
where python 2>nul
if %errorlevel% neq 0 (
    echo [错误] 未找到 Python，请先安装 Python 3.9+
    echo 下载地址: https://www.python.org/downloads/
    echo 安装时记得勾选 "Add Python to PATH"
    pause
    exit /b 1
)

python --version
echo.

:: 2. 创建 venv
if exist venv\ (
    echo [信息] venv 已存在，跳过创建
) else (
    echo [..] 创建虚拟环境...
    python -m venv venv
    if %errorlevel% neq 0 (
        echo [错误] 创建 venv 失败
        pause
        exit /b 1
    )
    echo [OK] venv 已创建
)

:: 3. 安装依赖
echo [..] 升级 pip...
venv\Scripts\python.exe -m pip install --upgrade pip -q

echo [..] 安装 Python 依赖...
venv\Scripts\pip.exe install -r requirements.txt -q
if %errorlevel% neq 0 (
    echo [错误] 依赖安装失败
    pause
    exit /b 1
)
echo [OK] 依赖安装完成

:: 4. 安装 Playwright 浏览器
echo [..] 安装 Playwright 浏览器（Chromium）...
venv\Scripts\python.exe -m playwright install chromium
echo [OK] Playwright 浏览器就绪

:: 5. 锁定依赖版本
venv\Scripts\pip.exe freeze > requirements-locked.txt 2>nul
echo [OK] 依赖版本已锁定到 requirements-locked.txt

echo.
echo ==============================================
echo   环境搭建完成！
echo   启动: start.bat
echo ==============================================
pause
