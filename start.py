#!/usr/bin/env python3
"""
B站数据采集 — 启动器

自动检测环境并启动图形界面。
双击即可运行（需已安装 Python）。
"""

import subprocess
import sys
import shutil
from pathlib import Path


def find_python():
    """找到可用的 Python 解释器（优先找 venv）"""
    script_dir = Path(__file__).parent.resolve()

    # 优先查找本地 venv
    venv_paths = [
        script_dir / "venv" / "bin" / "python3",
        script_dir / "venv" / "Scripts" / "python.exe",
    ]
    for p in venv_paths:
        if p.exists():
            return str(p)

    # 查找系统 Python
    for cmd in [sys.executable, "python3", "python"]:
        try:
            r = subprocess.run([cmd, "--version"], capture_output=True, text=True, timeout=5)
            if r.returncode == 0 and "Python 3" in r.stdout:
                return cmd
        except Exception:
            continue
    return None


def check_deps(python):
    """检查依赖是否安装"""
    try:
        r = subprocess.run(
            [python, "-c", "import playwright, aiohttp"],
            capture_output=True, timeout=10
        )
        return r.returncode == 0
    except Exception:
        return False


def install_deps(python):
    """安装依赖"""
    script_dir = Path(__file__).parent.resolve()
    venv_dir = script_dir / "venv"

    # 如果没有 venv，创建一个
    if not venv_dir.exists():
        print("[INFO] Creating virtual environment...")
        subprocess.run([python, "-m", "venv", str(venv_dir)], check=True)
        # 更新 python 路径到 venv
        if sys.platform == "win32":
            python = str(venv_dir / "Scripts" / "python.exe")
        else:
            python = str(venv_dir / "bin" / "python3")

    print("[1/2] Installing playwright...")
    subprocess.run([python, "-m", "pip", "install", "playwright", "-q"], check=True)
    print("[2/2] Installing aiohttp...")
    subprocess.run([python, "-m", "pip", "install", "aiohttp", "-q"], check=True)
    print("[OK] Dependencies installed")
    return python


def main():
    script_dir = Path(__file__).parent.resolve()
    gui_script = script_dir / "web_gui.py"

    if not gui_script.exists():
        print("[ERROR] web_gui.py not found")
        input("Press Enter to exit...")
        sys.exit(1)

    python = find_python()
    if not python:
        print("[ERROR] Python 3 not found")
        print("Please install Python 3.10+ from https://www.python.org/downloads/")
        print("Remember to check 'Add Python to PATH' during installation")
        input("Press Enter to exit...")
        sys.exit(1)

    print(f"[OK] Python: {python}")

    if not check_deps(python):
        print("[INFO] Dependencies not found, installing...")
        python = install_deps(python)

    print("[OK] Starting BiliCollector...")
    print("-" * 40)

    subprocess.run([python, str(gui_script)])


if __name__ == "__main__":
    main()
