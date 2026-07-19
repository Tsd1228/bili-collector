#!/bin/bash
# B站收藏夹数据分析项目 — 一键启动
# 自动检测 venv，无需手动激活

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# 优先用 venv 的 Python
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

exec "$PYTHON" start.py
