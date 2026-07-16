#!/usr/bin/env python3
"""
B站工具打包脚本

支持打包：
  - gui.py（图形界面版 — 推荐用户使用）
  - bilbil.py（命令行版）
  - bili_dynamic_crawler_simple.py（命令行版）

用法：
  python build.py              # 打包所有
  python build.py gui          # 只打包 GUI（推荐）
  python build.py bilbil       # 只打包收藏夹
  python build.py dynamic      # 只打包动态
"""

import subprocess
import sys
import platform
from pathlib import Path


TOOLS = {
    "gui": {
        "script": "web_gui.py",
        "name": "BiliCollector",
        "desc": "GUI",
    },
    "bilbil": {
        "script": "bilbil.py",
        "name": "bili_fav_extract",
        "desc": "CLI",
    },
    "dynamic": {
        "script": "bili_dynamic_crawler_simple.py",
        "name": "bili_dynamic",
        "desc": "CLI",
    },
}


def run_cmd(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    print(f"  > {' '.join(cmd)}")
    return subprocess.run(cmd, check=check)


def build_tool(tool_key: str):
    tool = TOOLS[tool_key]
    script = Path(tool["script"])

    if not script.exists():
        print(f"  ❌ 未找到 {script}")
        return False

    print(f"\n🔨 打包 {tool['desc']}: {tool['name']}")

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--clean",
        "--noconfirm",
        "--onefile",
        "--name", tool["name"],
    ]

    cmd.append(str(script))

    run_cmd(cmd)

    system = platform.system()
    ext = ".exe" if system == "Windows" else ""
    output = Path(f"dist/{tool['name']}{ext}")

    if output.exists():
        size_mb = output.stat().st_size / (1024 * 1024)
        print(f"  ✅ 成功: {output.resolve()} ({size_mb:.1f} MB)")
        return True
    else:
        print(f"  ❌ 失败: 未找到输出文件")
        return False


def main():
    system = platform.system()
    print(f"🖥️  系统: {system} ({platform.machine()})")
    print(f"📂 目录: {Path.cwd().resolve()}\n")

    # 检查 Python
    print("🐍 检查 Python 版本...")
    if sys.version_info < (3, 10):
        print(f"  ❌ 需要 Python 3.10+，当前: {sys.version}")
        sys.exit(1)
    print(f"  ✅ Python {sys.version.split()[0]}")

    # 安装依赖
    print("\n📦 安装依赖...")
    run_cmd([sys.executable, "-m", "pip", "install", "-r", "requirements.txt", "-q"])
    run_cmd([sys.executable, "-m", "pip", "install", "pyinstaller", "-q"])

    # 确定要打包的工具
    target = sys.argv[1] if len(sys.argv) > 1 else "all"

    if target == "all":
        tools_to_build = list(TOOLS.keys())
    elif target in TOOLS:
        tools_to_build = [target]
    else:
        print(f"\n❌ 未知工具: {target}")
        print(f"   可选: {', '.join(TOOLS.keys())}, all")
        sys.exit(1)

    # 打包
    results = {}
    for tool_key in tools_to_build:
        results[tool_key] = build_tool(tool_key)

    # 汇总
    print(f"\n{'=' * 50}")
    print("📋 打包结果汇总:")
    print(f"{'=' * 50}")
    for tool_key, success in results.items():
        status = "✅" if success else "❌"
        print(f"  {status} {TOOLS[tool_key]['desc']}: {TOOLS[tool_key]['name']}")

    print("\n📦 分发给用户:")
    print("  1. 将 dist/ 下的可执行文件发给用户")
    print("  2. 用户双击运行，无需安装任何东西")
    print("  3. 首次运行会自动下载 Chromium（约 150MB）")
    print("  4. 扫码登录 → 点击采集 → 完成")


if __name__ == "__main__":
    main()
