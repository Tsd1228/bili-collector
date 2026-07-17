#!/usr/bin/env python3
"""
B站动态爬虫（精简版）

功能：
  1. 爬取指定用户的全部动态
  2. 只输出转发动态的精简 JSON
  3. 支持断点续爬
  4. Cookie 从配置文件读取

用法：
  python bili_dynamic_crawler_simple.py
  python bili_dynamic_crawler_simple.py --uid 123456789
  python bili_dynamic_crawler_simple.py --reset  # 清除进度，重新爬取

配置文件：./dynamic_config.json
  {
    "uid": 123456789,
    "sessdata": "...",
    "bili_jct": "...",
    "buvid3": "..."
  }
"""

import argparse
import asyncio
import hashlib
import json
import os
import time
import urllib.parse
from pathlib import Path

import aiohttp

# ============================================================
# 📁 路径
# ============================================================

# 与 bili_common.py 保持一致：默认在脚本同级目录
_base_dir = Path(__file__).parent.resolve()
if os.environ.get("BILI_PORTABLE", "1") == "0":
    _base_dir = Path.home() / ".bilibili_fav"

BILI_FAV_HOME = _base_dir
CONFIG_FILE = BILI_FAV_HOME / "dynamic_config.json"

PAGE_SLEEP = 0.3
MAX_RETRIES = 3
RETRY_DELAY = 2.0


def _get_progress_file(uid: str) -> Path:
    """按 UID 隔离的进度文件"""
    return BILI_FAV_HOME / f"dynamic_progress_{uid}.json"


def _get_output_dir(uid: str) -> Path:
    """按 UID 隔离的输出目录"""
    return BILI_FAV_HOME / f"dynamics_{uid}"

# ============================================================
# 🔧 配置加载
# ============================================================


def load_config() -> dict:
    """加载配置文件"""
    if not CONFIG_FILE.exists():
        # 创建示例配置
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        example = {
            "uid": 123456789,
            "sessdata": "你的SESSDATA",
            "bili_jct": "你的bili_jct",
            "buvid3": "你的buvid3",
        }
        CONFIG_FILE.write_text(json.dumps(example, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[错误] 未找到配置文件，已创建示例: {CONFIG_FILE}")
        print("   请编辑配置文件填入你的 Cookie 信息后重新运行")
        exit(1)

    config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))

    # 验证必要字段
    required = ["uid", "sessdata", "bili_jct", "buvid3"]
    missing = [k for k in required if not config.get(k)]
    if missing:
        print(f"[错误] 配置文件缺少字段: {missing}")
        exit(1)

    return config


# ============================================================
#  进度管理
# ============================================================


def load_progress(uid: str) -> dict:
    progress_file = _get_progress_file(uid)
    if progress_file.exists():
        try:
            return json.loads(progress_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"offset": "", "page": 0, "items_count": 0}


def save_progress(uid: str, progress: dict):
    progress_file = _get_progress_file(uid)
    progress_file.parent.mkdir(parents=True, exist_ok=True)
    progress_file.write_text(json.dumps(progress, ensure_ascii=False, indent=2), encoding="utf-8")


# ============================================================
# 🔐 WBI 签名
# ============================================================


def wbi_sign(params: dict, img_key: str, sub_key: str) -> dict:
    params["wts"] = int(time.time())
    sorted_str = "&".join(
        f"{k}={urllib.parse.quote(str(v))}"
        for k, v in sorted(params.items())
    )
    s = sorted_str + img_key + sub_key
    params["w_rid"] = hashlib.md5(s.encode()).hexdigest()
    return params


# ============================================================
# 🛠 工具函数
# ============================================================


def ts_to_str(ts) -> str:
    if not ts:
        return None
    if isinstance(ts, str):
        if ts.isdigit():
            ts = int(ts)
        else:
            return None
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))


def simplify_dynamic(item: dict) -> dict:
    """精简单条动态"""
    try:
        modules = item.get("modules", {})
        author = modules.get("module_author", {})
        dynamic = modules.get("module_dynamic", {})
        stat = modules.get("module_stat", {})

        result = {
            "id": item.get("id_str"),
            "type": item.get("type"),
            "time": ts_to_str(author.get("pub_ts")),
            "author": author.get("name"),
            "content": None,
            "pictures": [],
            "video_bvid": None,
            "video_title": None,
            "likes": 0,
            "comments": 0,
            "reposts": 0,
            "is_forward": False,
            "forward_content": None,
            "original_author": None,
        }

        if stat:
            result["likes"] = (stat.get("like") or {}).get("count", 0)
            result["comments"] = (stat.get("comment") or {}).get("count", 0)
            result["reposts"] = (stat.get("forward") or {}).get("count", 0)

        # 转发动态
        if item.get("orig"):
            result["is_forward"] = True
            orig = item["orig"]
            orig_modules = orig.get("modules", {})
            orig_author = orig_modules.get("module_author", {})
            result["original_author"] = orig_author.get("name")

            desc = dynamic.get("desc", {})
            result["forward_content"] = desc.get("text")

            orig_dynamic = orig_modules.get("module_dynamic", {})
            major = orig_dynamic.get("major", {})
            major_type = major.get("type")

            if major_type == "MAJOR_TYPE_ARCHIVE":
                arc = major["archive"]
                result["type"] = "video"
                result["video_bvid"] = arc.get("bvid")
                result["video_title"] = arc.get("title")
                result["content"] = arc.get("desc")
            elif major_type == "MAJOR_TYPE_DRAW":
                draw = major["draw"]
                result["type"] = "image"
                result["pictures"] = [p.get("src") for p in draw.get("items", [])]

        else:
            return None

        if not result["content"]:
            desc = dynamic.get("desc", {})
            result["content"] = desc.get("text")

        return result

    except Exception as e:
        print(f"[警告] 解析异常: {e}")
        return None


# ============================================================
#  爬取逻辑
# ============================================================


async def crawl(config: dict, reset: bool = False):
    uid = str(config["uid"])
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Referer": f"https://space.bilibili.com/{uid}/",
        "Cookie": (
            f"SESSDATA={config['sessdata']}; "
            f"bili_jct={config['bili_jct']}; "
            f"buvid3={config['buvid3']}"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }

    # 按 UID 隔离的目录
    output_dir = _get_output_dir(uid)
    progress_file = _get_progress_file(uid)

    # 加载进度
    progress = load_progress(uid) if not reset else {"offset": "", "page": 0, "items_count": 0}
    existing_items = []

    # 如果有进度，加载已有数据
    simple_file = output_dir / f"uid_{uid}_simple.json"

    if not reset and simple_file.exists():
        try:
            existing_simple = json.loads(simple_file.read_text(encoding="utf-8"))
            print(f"📂 加载已有精简数据: {len(existing_simple)} 条")
        except Exception:
            existing_simple = []

    all_items = []
    offset = progress.get("offset", "")
    page_num = progress.get("page", 0)

    output_dir.mkdir(parents=True, exist_ok=True)

    async with aiohttp.ClientSession(headers=headers) as s:
        # 获取 WBI 密钥
        print("🔐 获取 WBI 密钥...")
        try:
            async with s.get("https://api.bilibili.com/x/web-interface/nav") as r:
                j = await r.json()
            img_key = j["data"]["wbi_img"]["img_url"].split("/")[-1].split(".")[0]
            sub_key = j["data"]["wbi_img"]["sub_url"].split("/")[-1].split(".")[0]
        except Exception as e:
            print(f"[错误] 获取 WBI 密钥失败: {e}")
            return

        while True:
            page_num += 1
            print(f"  正在爬取第 {page_num} 页动态...")

            params = {
                "host_mid": uid,
                "offset": offset,
                "timezone_offset": -480,
            }
            params = wbi_sign(params, img_key, sub_key)

            url = "https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/space"

            # 带重试的请求
            js = None
            for attempt in range(MAX_RETRIES):
                try:
                    async with s.get(url, params=params) as r:
                        if r.status == 200:
                            js = await r.json()
                            break
                        elif r.status == 412:
                            wait = RETRY_DELAY * (2 ** attempt)
                            print(f"[警告] 请求被限流（412），等待 {wait:.1f}s 后重试...")
                            await asyncio.sleep(wait)
                        else:
                            print(f"[错误] HTTP 状态码: {r.status}")
                            break
                except Exception as e:
                    wait = RETRY_DELAY * (2 ** attempt)
                    print(f"[警告] 请求异常: {e}，等待 {wait:.1f}s 后重试...")
                    await asyncio.sleep(wait)

            if js is None:
                print("[错误] 请求失败，停止爬取")
                break

            if js.get("code") != 0:
                print(f"[错误] API 返回错误: {js.get('message')}")
                break

            data = js.get("data", {})
            items = data.get("items", [])

            if not items:
                print("  未获取到更多动态，爬取结束。")
                break

            all_items.extend(items)

            # 保存进度
            has_more = data.get("has_more", 0)
            offset = data.get("offset", "")

            progress = {
                "offset": offset,
                "page": page_num,
                "items_count": len(all_items),
            }
            save_progress(uid, progress)

            # 增量保存原始数据
            simple_file.write_text(json.dumps(all_items, ensure_ascii=False, indent=2), encoding="utf-8")

            print(f"     本页 {len(items)} 条，累计 {len(all_items)} 条")

            if has_more != 1 or not offset:
                print("  已无更多动态，爬取完成。")
                break

            await asyncio.sleep(PAGE_SLEEP)

    # 导出精简版（只保留转发动态）
    simplified = []
    for item in all_items:
        simple = simplify_dynamic(item)
        if simple:
            simplified.append(simple)

    simple_file.write_text(json.dumps(simplified, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n  转发动态: {len(simplified)} 条 -> {simple_file}")

    # 清理进度文件
    if progress_file.exists():
        progress_file.unlink()
        print("🧹 进度文件已清理")


# ============================================================
# 🏁 入口
# ============================================================


def main():
    parser = argparse.ArgumentParser(description="B站动态爬虫")
    parser.add_argument("--uid", type=int, help="覆盖配置中的 UID")
    parser.add_argument("--reset", action="store_true", help="清除进度，重新爬取")
    args = parser.parse_args()

    config = load_config()
    if args.uid:
        config["uid"] = args.uid

    asyncio.run(crawl(config, reset=args.reset))


if __name__ == "__main__":
    main()
