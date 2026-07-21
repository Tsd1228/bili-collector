#!/bin/bash
# B站收藏夹数据分析项目 — 启动 Web GUI
# 自动检测 venv，未安装依赖时自动运行 setup.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# 杀掉已有 web_gui 进程释放端口
fuser -k 18234/tcp 2>/dev/null || true

# 找 Python
PYTHON=""
if [ -f "venv/bin/python3" ]; then
    PYTHON="venv/bin/python3"
elif [ -f "venv/Scripts/python.exe" ]; then
    PYTHON="venv/Scripts/python.exe"
else
    for cmd in python3 python; do
        if command -v "$cmd" &>/dev/null; then
            PYTHON="$cmd"
            break
        fi
    done
fi

if [ -z "$PYTHON" ]; then
    echo "[错误] 找不到 Python 3"
    exit 1
fi

# 检查 playwright 是否可用
if ! "$PYTHON" -c "import playwright" 2>/dev/null; then
    echo "[..] Playwright 未安装，运行 setup.sh..."
    bash setup.sh
fi

exec "$PYTHON" web_gui.py
