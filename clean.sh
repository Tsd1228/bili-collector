#!/bin/bash
# B站收藏夹数据分析项目 — 清理所有生成数据
# 用法: bash clean.sh
# 效果: 删除所有爬取数据、数据库、报告、缓存，保留代码和 venv

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "=============================================="
echo "  清理生成数据"
echo "=============================================="

# 用户数据
rm -rf data_*/
rm -rf user_data_*/
rm -rf user_data_temp
rm -f bili_uid.txt
rm -f folders.json
rm -f *.db

# 分析报告与文案
rm -f analysis_report_*.json
rm -f analysis_report_*.html
rm -f analysis_report_*.txt
rm -f copy_*.json

# 运行时状态
rm -f dynamic_config.json
rm -f dynamic_progress*.json

# LLM 配置（用户敏感信息）
rm -f llm_config.json

# 输出目录
rm -rf outbox/

# Python 缓存
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
find . -type f -name "*.pyc" -delete 2>/dev/null

echo "[OK] 全部清理完成"
echo "    保留: venv/  requirements*.txt  setup.sh  start.sh"
echo "    代码文件不受影响"
