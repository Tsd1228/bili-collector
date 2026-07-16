#!/usr/bin/env python3
"""
B站数据接口模块 — 供外部模块调用

功能：
  - 登录管理（首次扫码 / 检测登录状态 / 换号）
  - 按 UID 触发收藏夹/动态采集
  - 读取缓存的 JSON 数据
  - 支持多用户隔离

用法：
  from data_interface import login, get_current_uid, update_favorites, get_favorites

  # 检查是否已登录
  uid = get_current_uid()

  # 需要登录（弹出浏览器扫码）
  uid = login()

  # 采集数据
  data = update_favorites(uid=uid)

  # 读缓存
  data = get_favorites(uid=uid)
"""

import json
import logging
from pathlib import Path

log = logging.getLogger("bili_interface")

# ============================================================
# 📁 路径工具
# ============================================================

BILI_FAV_HOME = Path.home() / ".bilibili_fav"
UID_FILE = BILI_FAV_HOME / "bili_uid.txt"


def _get_data_dir(uid: str) -> Path:
    """按 UID 获取收藏夹数据目录"""
    return BILI_FAV_HOME / f"data_{uid}"


def _get_dynamics_dir(uid: str) -> Path:
    """按 UID 获取动态数据目录"""
    return BILI_FAV_HOME / f"dynamics_{uid}"


# ============================================================
# 🔐 登录管理
# ============================================================


def get_current_uid() -> str | None:
    """获取当前已登录的 UID，未登录返回 None"""
    # 自动迁移旧目录
    _migrate_old_dirs()
    
    if not UID_FILE.exists():
        return None
    uid = UID_FILE.read_text().strip()
    if not uid:
        return None
    user_dir = BILI_FAV_HOME / f"user_data_{uid}"
    if not user_dir.exists():
        return None
    return uid


def _migrate_old_dirs():
    """自动迁移旧目录结构到新结构"""
    import shutil
    
    # 迁移 user_data → user_data_{uid}
    old_user_dir = BILI_FAV_HOME / "user_data"
    if old_user_dir.exists() and UID_FILE.exists():
        uid = UID_FILE.read_text().strip()
        if uid:
            new_user_dir = BILI_FAV_HOME / f"user_data_{uid}"
            if not new_user_dir.exists():
                shutil.move(str(old_user_dir), str(new_user_dir))
                log.info(f"迁移目录: user_data → user_data_{uid}")
    
    # 迁移 data → data_{uid}
    old_data_dir = BILI_FAV_HOME / "data"
    if old_data_dir.exists() and UID_FILE.exists():
        uid = UID_FILE.read_text().strip()
        if uid:
            new_data_dir = BILI_FAV_HOME / f"data_{uid}"
            if not new_data_dir.exists():
                shutil.move(str(old_data_dir), str(new_data_dir))
                log.info(f"迁移目录: data → data_{uid}")


def login() -> str:
    """扫码登录，返回 UID。
    
    首次使用会弹出浏览器窗口，请用 B站 APP 扫码。
    登录成功后会自动关闭浏览器。
    """
    from bili_common import do_login as _do_login
    from playwright.sync_api import sync_playwright

    print("=" * 50)
    print("🔐 B站扫码登录")
    print("=" * 50)
    print()
    print("即将弹出浏览器窗口，请用 B站 APP 扫码登录。")
    print("登录成功后会自动关闭浏览器。")
    print()

    with sync_playwright() as p:
        uid = _do_login(p)

    print(f"\n✅ 登录成功！UID: {uid}")
    return uid


def list_users() -> list[str]:
    """列出所有已登录的 UID"""
    if not BILI_FAV_HOME.exists():
        return []

    uids = []
    for item in BILI_FAV_HOME.iterdir():
        if item.is_dir() and item.name.startswith("user_data_"):
            uid = item.name[10:]  # 去掉 "user_data_" 前缀
            uids.append(uid)

    return sorted(uids)


# ============================================================
# 📂 收藏夹数据
# ============================================================


def get_favorites(uid: str) -> dict:
    """读取指定 UID 的收藏夹缓存数据。
    
    返回格式：
    {
        "uid": "229558048",
        "favorites": [
            {
                "name": "收藏夹名称",
                "videos": [...],
                "file": "xxx.json"
            },
            ...
        ]
    }
    """
    data_dir = _get_data_dir(uid)
    
    if not data_dir.exists():
        log.warning(f"UID {uid} 无缓存数据: {data_dir}")
        return {"uid": uid, "favorites": []}
    
    favorites = []
    for json_file in sorted(data_dir.glob("*.json")):
        if json_file.name.startswith("."):
            continue
        try:
            videos = json.loads(json_file.read_text(encoding="utf-8"))
            favorites.append({
                "name": json_file.stem,
                "videos": videos,
                "file": str(json_file),
            })
        except Exception as e:
            log.error(f"读取失败 {json_file}: {e}")
    
    return {"uid": uid, "favorites": favorites}


def update_favorites(uid: str, visible: bool = False, manual: bool = False,
                     reset: bool = False, fav_name: str = None) -> dict:
    """触发收藏夹采集并返回数据。
    
    Args:
        uid: B站用户 UID
        visible: 有头浏览器模式
        manual: 手动模式
        reset: 清除进度，重新提取
        fav_name: 只提取指定收藏夹名称
    
    Returns:
        与 get_favorites() 相同格式
    """
    from bilbil import collect_favorites
    
    log.info(f"触发收藏夹采集 | UID: {uid}")
    videos_list = collect_favorites(
        uid=uid,
        visible=visible,
        manual=manual,
        reset=reset,
        fav_name=fav_name,
    )
    
    # 读取刚生成的数据返回
    return get_favorites(uid)


# ============================================================
# 📊 动态数据
# ============================================================


def get_dynamics(uid: str) -> dict:
    """读取指定 UID 的动态缓存数据。
    
    返回格式：
    {
        "uid": "229558048",
        "dynamics": [...],
        "count": 123
    }
    """
    dynamics_dir = _get_dynamics_dir(uid)
    simple_file = dynamics_dir / f"uid_{uid}_simple.json"
    
    if not simple_file.exists():
        log.warning(f"UID {uid} 无动态缓存: {simple_file}")
        return {"uid": uid, "dynamics": [], "count": 0}
    
    try:
        dynamics = json.loads(simple_file.read_text(encoding="utf-8"))
        return {"uid": uid, "dynamics": dynamics, "count": len(dynamics)}
    except Exception as e:
        log.error(f"读取动态数据失败: {e}")
        return {"uid": uid, "dynamics": [], "count": 0}


def update_dynamics(uid: str, reset: bool = False) -> dict:
    """触发动态采集并返回数据。
    
    注意：动态采集需要 Cookie 配置。
    配置文件位于 ~/.bilibili_fav/dynamic_config.json
    
    Args:
        uid: B站用户 UID
        reset: 清除进度，重新爬取
    
    Returns:
        与 get_dynamics() 相同格式
    """
    import subprocess
    import sys
    
    log.info(f"触发动态采集 | UID: {uid}")
    
    # 构建命令
    cmd = [sys.executable, "bili_dynamic_crawler_simple.py", "--uid", str(uid)]
    if reset:
        cmd.append("--reset")
    
    # 执行采集
    try:
        subprocess.run(cmd, check=True, cwd=str(Path(__file__).parent))
    except subprocess.CalledProcessError as e:
        log.error(f"动态采集失败: {e}")
    
    # 读取刚生成的数据返回
    return get_dynamics(uid)


# ============================================================
# 📋 工具函数
# ============================================================


def get_user_summary(uid: str) -> dict:
    """获取指定用户的数据摘要"""
    fav_data = get_favorites(uid)
    dyn_data = get_dynamics(uid)
    
    total_videos = sum(len(f["videos"]) for f in fav_data["favorites"])
    
    return {
        "uid": uid,
        "favorites_count": len(fav_data["favorites"]),
        "total_videos": total_videos,
        "dynamics_count": dyn_data["count"],
    }
