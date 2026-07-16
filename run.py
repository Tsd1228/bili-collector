#!/usr/bin/env python3
"""
B站数据采集 — 一键运行

首次运行：弹出浏览器扫码登录 → 自动获取 UID → 采集数据
后续运行：自动使用已保存的登录态

用法：
  python run.py                  # 自动检测登录状态
  python run.py --login          # 强制重新登录（换号用）
  python run.py --fav-only       # 只采集收藏夹
  python run.py --dyn-only       # 只采集动态
  python run.py --list           # 查看已登录的用户
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# 便携模式：默认在脚本同级目录
_base_dir = Path(__file__).parent.resolve()
if os.environ.get("BILI_PORTABLE", "1") == "0":
    _base_dir = Path.home() / ".bilibili_fav"

BILI_FAV_HOME = _base_dir
UID_FILE = BILI_FAV_HOME / "bili_uid.txt"


def check_login() -> str | None:
    """检查是否已登录，返回 UID 或 None"""
    if not UID_FILE.exists():
        return None
    uid = UID_FILE.read_text().strip()
    if not uid:
        return None
    # 检查对应的 user_data 目录是否存在
    user_dir = BILI_FAV_HOME / f"user_data_{uid}"
    if not user_dir.exists():
        return None
    return uid


def do_login() -> str:
    """扫码登录，返回 UID"""
    print("=" * 50)
    print("🔐 首次使用，需要扫码登录 B站")
    print("=" * 50)
    print()
    print("即将弹出浏览器窗口，请用 B站 APP 扫码登录。")
    print("登录成功后会自动关闭浏览器并开始采集。")
    print()

    from bili_common import do_login as _do_login
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        uid = _do_login(p)

    print(f"\n✅ 登录成功！UID: {uid}")
    return uid


def list_users():
    """列出所有已登录的用户"""
    if not BILI_FAV_HOME.exists():
        print("暂无已登录用户")
        return

    users = []
    for item in BILI_FAV_HOME.iterdir():
        if item.is_dir() and item.name.startswith("user_data_"):
            uid = item.name[10:]  # 去掉 "user_data_" 前缀
            users.append(uid)

    if not users:
        print("暂无已登录用户")
        return

    print("已登录用户:")
    for uid in users:
        # 检查是否有数据
        data_dir = BILI_FAV_HOME / f"data_{uid}"
        has_data = data_dir.exists() and any(data_dir.glob("*.json"))
        status = "✅ 有数据" if has_data else "⚪ 未采集"
        print(f"  UID: {uid}  [{status}]")


def main():
    parser = argparse.ArgumentParser(description="B站数据采集一键运行")
    parser.add_argument("--login", action="store_true", help="强制重新登录（换号用）")
    parser.add_argument("--fav-only", action="store_true", help="只采集收藏夹")
    parser.add_argument("--dyn-only", action="store_true", help="只采集动态")
    parser.add_argument("--visible", action="store_true", help="有头浏览器（调试用）")
    parser.add_argument("--reset", action="store_true", help="清除进度，重新采集")
    parser.add_argument("--list", action="store_true", help="查看已登录用户")
    args = parser.parse_args()

    # 查看已登录用户
    if args.list:
        list_users()
        return

    # 检查登录状态
    uid = None
    if not args.login:
        uid = check_login()

    # 需要登录
    if not uid:
        try:
            uid = do_login()
        except Exception as e:
            print(f"\n❌ 登录失败: {e}")
            print("请检查网络连接后重试")
            sys.exit(1)

    run_fav = not args.dyn_only
    run_dyn = not args.fav_only

    print(f"\n{'=' * 50}")
    print(f"🎯 目标 UID: {uid}")
    print(f"   收藏夹: {'✅' if run_fav else '⏭️  跳过'}")
    print(f"   动态:   {'✅' if run_dyn else '⏭️  跳过'}")
    print(f"{'=' * 50}\n")

    # ---- 收藏夹 ----
    if run_fav:
        print("📦 开始采集收藏夹...\n")
        try:
            from bilbil import collect_favorites
            videos = collect_favorites(
                uid=uid,
                visible=args.visible,
                reset=args.reset,
            )
            total = sum(len(v) for v in videos) if videos else 0
            print(f"\n✅ 收藏夹采集完成，共 {total} 个视频\n")
        except Exception as e:
            print(f"\n❌ 收藏夹采集失败: {e}\n")

    # ---- 动态 ----
    if run_dyn:
        print("📦 开始采集动态...\n")
        try:
            import asyncio
            from bili_dynamic_crawler_simple import crawl

            # 动态采集需要 Cookie，从登录态获取
            config = _get_dynamic_config(uid)
            if config:
                asyncio.run(crawl(config, reset=args.reset))
                print(f"\n✅ 动态采集完成\n")
            else:
                print(f"\n⚠️  动态采集需要 Cookie 配置")
                print(f"   请手动配置: ~/.bilibili_fav/dynamic_config.json")
                print(f"   或跳过动态采集: python run.py --fav-only\n")
        except Exception as e:
            print(f"\n❌ 动态采集失败: {e}\n")

    # ---- 汇总 ----
    from data_interface import get_user_summary
    summary = get_user_summary(uid)
    print(f"{'=' * 50}")
    print(f"📊 UID {uid} 数据汇总:")
    print(f"   收藏夹数量: {summary['favorites_count']}")
    print(f"   视频总数:   {summary['total_videos']}")
    print(f"   动态总数:   {summary['dynamics_count']}")
    print(f"{'=' * 50}")


def _get_dynamic_config(uid: str) -> dict | None:
    """获取动态采集的 Cookie 配置。
    
    优先从 dynamic_config.json 读取，
    如果不存在则尝试从浏览器上下文提取。
    """
    config_file = BILI_FAV_HOME / "dynamic_config.json"

    # 有配置文件直接用
    if config_file.exists():
        try:
            config = json.loads(config_file.read_text(encoding="utf-8"))
            if config.get("sessdata"):
                config["uid"] = uid
                return config
        except Exception:
            pass

    # 没有配置文件，尝试从浏览器提取 Cookie
    print("🔧 尝试从浏览器登录态提取 Cookie...")
    try:
        cookies = _extract_cookies_from_browser(uid)
        if cookies:
            config = {
                "uid": uid,
                "sessdata": cookies.get("SESSDATA", ""),
                "bili_jct": cookies.get("bili_jct", ""),
                "buvid3": cookies.get("buvid3", ""),
            }
            # 保存配置
            config_file.parent.mkdir(parents=True, exist_ok=True)
            config_file.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"✅ Cookie 已保存到 {config_file}")
            return config
    except Exception as e:
        print(f"⚠️  提取 Cookie 失败: {e}")

    return None


def _extract_cookies_from_browser(uid: str) -> dict | None:
    """从 Chromium 浏览器上下文提取 Cookie"""
    from playwright.sync_api import sync_playwright
    from bili_common import get_user_dir

    user_dir = get_user_dir(uid)
    if not user_dir.exists():
        return None

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(user_dir),
            headless=True,
            args=["--no-sandbox"],
        )
        page = context.pages[0] if context.pages else context.new_page()

        # 访问 B站获取 Cookie
        page.goto("https://www.bilibili.com", timeout=30_000)
        page.wait_for_timeout(3000)

        # 提取 Cookie
        all_cookies = context.cookies()
        cookie_dict = {c["name"]: c["value"] for c in all_cookies}

        context.close()

    # 检查必要字段
    if cookie_dict.get("SESSDATA"):
        return cookie_dict

    return None


if __name__ == "__main__":
    main()
