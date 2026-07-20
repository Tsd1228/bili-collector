#!/bin/bash
# B站收藏夹数据分析项目 — 环境搭建脚本
# 用法: bash setup.sh
# 功能: 创建 venv → 安装依赖 → 安装 Playwright 浏览器

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# 国内镜像源（Tuna 清华源，下载慢时可换阿里云：https://mirrors.aliyun.com/pypi/simple/）
PIP_MIRROR="https://pypi.tuna.tsinghua.edu.cn/simple"
PIP_TRUST="--trusted-host pypi.tuna.tsinghua.edu.cn"

echo "=============================================="
echo "  B站收藏夹数据分析项目 — 环境搭建"
echo "=============================================="
echo ""

# 1. 找 Python 3
PYTHON=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        v=$("$cmd" --version 2>&1)
        if echo "$v" | grep -q "Python 3"; then
            PYTHON="$cmd"
            echo "[OK] Python: $v"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    echo "[错误] 未找到 Python 3，请先安装 Python 3.9+"
    exit 1
fi

# 2. 创建 venv
if [ -d "venv" ]; then
    echo "[信息] venv 已存在，跳过创建"
else
    echo "[..] 创建虚拟环境..."
    $PYTHON -m venv venv
    echo "[OK] venv 已创建"
fi

# 3. 激活并安装依赖
source venv/bin/activate

echo "[..] 升级 pip..."
pip install --upgrade pip -q -i "$PIP_MIRROR" $PIP_TRUST

echo "[..] 安装 Python 依赖..."
pip install -r requirements.txt -q -i "$PIP_MIRROR" $PIP_TRUST

echo "[OK] 依赖安装完成"

# 4. 安装 Playwright 浏览器
echo "[..] 安装 Playwright 浏览器（Chromium）..."
python -m playwright install chromium 2>/dev/null || playwright install chromium 2>/dev/null
echo "[OK] Playwright 浏览器就绪"

# 5. 检查 ffmpeg（可选，用于视频处理）
if command -v ffmpeg &>/dev/null; then
    echo "[OK] ffmpeg 可用"
else
    echo "[可选] ffmpeg 未安装，项目基础功能不受影响"
fi

# 6. 锁定依赖版本
pip freeze > requirements-locked.txt 2>/dev/null
echo "[OK] 依赖版本已锁定到 requirements-locked.txt"

echo ""
echo "=============================================="
echo "  环境搭建完成！"
echo "  启动: bash start.sh"
echo "  或:   source venv/bin/activate && python start.py"
echo "=============================================="
