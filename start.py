#!/usr/bin/env python3
"""
B站数据采集 — 一键运行脚本

自动完成：登录 → 采集 → 分析 → 文案 → HTML导出
跑完即止，约 4 分钟。
"""

import subprocess
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()


def find_python():
    """找到可用的 Python 解释器（优先找 venv）"""
    venv_paths = [
        SCRIPT_DIR / "venv" / "bin" / "python3",
        SCRIPT_DIR / "venv" / "Scripts" / "python.exe",
    ]
    for p in venv_paths:
        if p.exists():
            return str(p)
    for cmd in [sys.executable, "python3", "python"]:
        try:
            r = subprocess.run([cmd, "--version"], capture_output=True, text=True, timeout=5)
            if r.returncode == 0 and "Python 3" in r.stdout:
                return cmd
        except Exception:
            continue
    return None


def run(cmd, desc="", timeout=300):
    """运行命令并打印"""
    if desc:
        print(f"\n[{desc}]")
    print(f"  {' '.join(cmd)}")
    t0 = time.time()
    r = subprocess.run(cmd, timeout=timeout)
    t = time.time() - t0
    print(f"  → {t:.0f}s, exit={r.returncode}")
    return r.returncode


def check_llm(python):
    """检测 LLM 配置，未配置则引导用户选择"""
    cfg_script = str(SCRIPT_DIR / "llm_config.py")

    r = subprocess.run([python, cfg_script, "--status"], capture_output=True, text=True, timeout=15)
    status_out = r.stdout + r.stderr

    if "Ollama" in status_out and "运行中" in status_out:
        print("[OK] LLM: Ollama 本地模型可用")
        return

    if "API Key" in status_out and "未设置" not in status_out:
        print("[OK] LLM: 云端模型已配置")
        return

    # 未配置，引导用户选择
    print("\n" + "=" * 50)
    print("  LLM 未配置，请选择分析用的模型")
    print("=" * 50)
    print()
    print("  [1] 本地 Ollama（需已安装并运行 ollama serve）")
    print("  [2] DeepSeek（推荐，需 API Key）")
    print("  [3] SiliconFlow（国内多模型）")
    print("  [4] OpenAI（GPT 系列）")
    print()
    choice = input("请选择 (1-4): ").strip()

    if choice == "1":
        import json
        cfg_path = SCRIPT_DIR / "llm_config.json"
        cfg = json.loads(cfg_path.read_text()) if cfg_path.exists() else {}
        cfg["provider"] = "ollama"
        cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2))
        print("[OK] 已选择 Ollama（请确保 ollama serve 已在运行）")
    elif choice == "2":
        key = input("  输入 DeepSeek API Key: ").strip()
        if key:
            import json
            cfg_path = SCRIPT_DIR / "llm_config.json"
            cfg = json.loads(cfg_path.read_text()) if cfg_path.exists() else {}
            cfg["provider"] = "deepseek"
            cfg["deepseek"] = {"api_key": key, "api_base": "https://api.deepseek.com/v1", "model": "deepseek-chat"}
            cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2))
            print("[OK] 已配置 DeepSeek")
    elif choice == "3":
        key = input("  输入 SiliconFlow API Key: ").strip()
        if key:
            import json
            cfg_path = SCRIPT_DIR / "llm_config.json"
            cfg = json.loads(cfg_path.read_text()) if cfg_path.exists() else {}
            cfg["provider"] = "siliconflow"
            cfg["siliconflow"] = {"api_key": key, "api_base": "https://api.siliconflow.cn/v1", "model": "Qwen/Qwen2.5-7B-Instruct"}
            cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2))
            print("[OK] 已配置 SiliconFlow")
    elif choice == "4":
        key = input("  输入 OpenAI API Key: ").strip()
        if key:
            import json
            cfg_path = SCRIPT_DIR / "llm_config.json"
            cfg = json.loads(cfg_path.read_text()) if cfg_path.exists() else {}
            cfg["provider"] = "openai"
            cfg["openai"] = {"api_key": key, "api_base": "https://api.openai.com/v1", "model": "gpt-4o-mini"}
            cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2))
            print("[OK] 已配置 OpenAI")
    else:
        print("[警告] 未选择，分析步骤可能失败")
    print()


def main():
    python = find_python()
    if not python:
        print("[错误] 找不到 Python 3")
        sys.exit(1)
    print(f"Python: {python}")

    # 先配好 LLM
    check_llm(python)

    total_start = time.time()

    # 步骤 1：采集（含登录）
    rc = run([python, str(SCRIPT_DIR / "bilbil.py"), "--visible"],
             desc="1/4 采集收藏夹（浏览器会打开，扫码登录）", timeout=360)
    if rc != 0:
        print("[错误] 采集失败")
        sys.exit(1)

    # 步骤 2：分析
    rc = run([python, str(SCRIPT_DIR / "analyze.py")],
             desc="2/4 分析兴趣画像", timeout=180)
    if rc != 0:
        print("[错误] 分析失败")
        sys.exit(1)

    # 步骤 3：文案
    rc = run([python, str(SCRIPT_DIR / "analyze.py"), "--copy"],
             desc="3/4 生成成分文案", timeout=120)
    if rc != 0:
        print("[警告] 文案生成失败（跳过）")

    # 步骤 4：导出 HTML
    rc = run([python, str(SCRIPT_DIR / "analyze.py"), "--export-html",
              "--output", str(SCRIPT_DIR / "analysis_report.html")],
             desc="4/4 导出 HTML 报告", timeout=30)

    total = time.time() - total_start
    print(f"\n{'=' * 50}")
    print(f"  全部完成！耗时 {total:.0f}s")
    print(f"  HTML 报告: {SCRIPT_DIR / 'analysis_report.html'}")
    print(f"{'=' * 50}")

    # 自动启动 Web GUI
    print(f"\n{'─' * 50}")
    print("  Web 界面启动中...")
    try:
        subprocess.Popen([python, str(SCRIPT_DIR / "web_gui.py")])
        print("  → http://localhost:18234")
        print("  关闭页面即可退出")
    except Exception as e:
        print(f"  [警告] Web 界面启动失败: {e}")


if __name__ == "__main__":
    main()
