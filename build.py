#!/usr/bin/env python3
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


def run_cmd(cmd, check=True):
    print(f"  > {' '.join(cmd)}")
    return subprocess.run(cmd, check=check)


def build_tool(tool_key):
    tool = TOOLS[tool_key]
    script = Path(tool["script"])

    if not script.exists():
        print(f"  [FAIL] not found: {script}")
        return False

    print(f"\n[BUILD] {tool['desc']}: {tool['name']}")

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--clean",
        "--noconfirm",
        "--onefile",
        "--name", tool["name"],
        str(script),
    ]

    run_cmd(cmd)

    system = platform.system()
    ext = ".exe" if system == "Windows" else ""
    output = Path(f"dist/{tool['name']}{ext}")

    if output.exists():
        size_mb = output.stat().st_size / (1024 * 1024)
        print(f"  [OK] {output.resolve()} ({size_mb:.1f} MB)")
        return True
    else:
        print(f"  [FAIL] output not found")
        return False


def main():
    system = platform.system()
    print(f"[SYS] {system} ({platform.machine()})")
    print(f"[DIR] {Path.cwd().resolve()}\n")

    print("[CHECK] Python version...")
    if sys.version_info < (3, 10):
        print(f"  [FAIL] need Python 3.10+, got {sys.version}")
        sys.exit(1)
    print(f"  [OK] Python {sys.version.split()[0]}")

    print("\n[DEPS] installing...")
    run_cmd([sys.executable, "-m", "pip", "install", "aiohttp", "-q"])
    run_cmd([sys.executable, "-m", "pip", "install", "pyinstaller", "-q"])

    target = sys.argv[1] if len(sys.argv) > 1 else "all"

    if target == "all":
        tools_to_build = list(TOOLS.keys())
    elif target in TOOLS:
        tools_to_build = [target]
    else:
        print(f"\n[FAIL] unknown tool: {target}")
        print(f"  available: {', '.join(TOOLS.keys())}, all")
        sys.exit(1)

    results = {}
    for tool_key in tools_to_build:
        results[tool_key] = build_tool(tool_key)

    print(f"\n{'=' * 50}")
    print("[SUMMARY]")
    print(f"{'=' * 50}")
    for tool_key, success in results.items():
        status = "[OK]" if success else "[FAIL]"
        print(f"  {status} {TOOLS[tool_key]['desc']}: {TOOLS[tool_key]['name']}")


if __name__ == "__main__":
    main()
