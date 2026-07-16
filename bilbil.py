#!/usr/bin/env python3
"""
B站收藏夹数据提取工具

功能：
  1. 扫码登录（首次需要）
  2. 列出用户所有收藏目录
  3. 通过 DOM 提取每个收藏夹的视频数据（标题、UP主、播放量、时长）
  4. 输出结构化 JSON，支持断点续传

用法：
  python bilbil.py                  # headless 自动模式
  python bilbil.py --visible        # 有头浏览器，自动操作
  python bilbil.py --manual         # 有头浏览器，你手动操作
  python bilbil.py --reset          # 清除进度，重新提取
"""

import argparse
import json
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

from bili_common import (
    BILI_FAV_HOME, get_data_dir, get_user_dir, get_progress_file,
    log, ensure_dir, safe_filename, retry,
    check_chromium, install_chromium, get_uid,
    fetch_favorites, build_fav_url, print_fav_list,
    scroll_to_bottom, load_progress, save_progress,
    mark_done, is_done, create_browser_context, navigate_to_fav,
)

# ============================================================
# 🔍 DOM 提取 JS
# ============================================================

EXTRACT_VIDEOS_JS = """
() => {
    const cards = document.querySelectorAll('.bili-video-card');
    const videos = [];

    for (const card of cards) {
        const titleEl = card.querySelector('.bili-video-card__title');
        const title = titleEl ? titleEl.textContent.trim() : '';

        const authorEl = card.querySelector('.bili-video-card__author');
        const authorRaw = authorEl ? authorEl.textContent.trim() : '';

        const linkEl = card.querySelector('.bili-cover-card');
        const link = linkEl ? linkEl.getAttribute('href') : '';

        const statEls = card.querySelectorAll('.bili-cover-card__stat');
        const statTexts = Array.from(statEls).map(el => el.textContent.trim());

        if (title) {
            videos.push({
                title,
                author_raw: authorRaw,
                link,
                stats_parts: statTexts,
            });
        }
    }
    return videos;
}
"""

# ============================================================
# 📊 数据解析 & 校验
# ============================================================


def parse_author(author_raw: str) -> str:
    """从 '百家讲堂_ · 收藏于昨天' 中提取作者名"""
    for sep in ["·", "•", " "]:
        if sep in author_raw:
            return author_raw.split(sep)[0].strip()
    return author_raw.strip()


def parse_stats(video: dict) -> dict:
    """解析统计信息"""
    parts = video.get("stats_parts", [])

    plays = ""
    duration = ""
    danmaku = ""

    if len(parts) >= 3:
        plays, danmaku, duration = parts[0], parts[1], parts[2]
    elif len(parts) == 2:
        plays, duration = parts[0], parts[1]
    elif parts:
        # 正则拆分拼接字符串
        raw = parts[0]
        m = re.match(r"([\d,.]+万?)(\d+)(\d{1,2}:\d{2}(?::\d{2})?)", raw)
        if m:
            plays, danmaku, duration = m.group(1), m.group(2), m.group(3)
        else:
            m2 = re.match(r"([\d,.]+万?)", raw)
            if m2:
                plays = m2.group(1)

    return {
        "title": video.get("title", ""),
        "author": parse_author(video.get("author_raw", "")),
        "plays": plays,
        "danmaku": danmaku,
        "duration": duration,
        "link": video.get("link", ""),
    }


def validate_video(video: dict) -> bool:
    """校验视频数据是否有效"""
    if not video.get("title"):
        return False
    if len(video["title"]) < 2:
        return False
    return True


def extract_videos_from_page(page) -> list[dict]:
    """从当前页面 DOM 提取所有视频信息"""
    raw_videos = page.evaluate(EXTRACT_VIDEOS_JS)
    videos = [parse_stats(v) for v in raw_videos]
    valid = [v for v in videos if validate_video(v)]
    if len(valid) < len(videos):
        log.warning(f"过滤无效视频: {len(videos) - len(valid)} 个")
    return valid


# ============================================================
# 🚀 核心采集函数（供外部调用）
# ============================================================

MAX_SCROLLS = 15


def collect_favorites(uid: str, visible: bool = False, manual: bool = False,
                      reset: bool = False, fav_name: str = None) -> list[dict]:
    """采集指定 UID 的收藏夹数据。
    
    Args:
        uid: B站用户 UID
        visible: 有头浏览器模式
        manual: 手动模式（需要人工操作）
        reset: 清除进度，重新提取
        fav_name: 只提取指定收藏夹名称
    
    Returns:
        所有收藏夹的视频数据列表
    """
    is_visible = visible or manual
    is_manual = manual
    
    data_dir = get_data_dir(uid)
    user_dir = get_user_dir(uid)
    progress_file = get_progress_file(uid)
    
    ensure_dir(data_dir)
    ensure_dir(user_dir)
    
    # 优先用本地浏览器，没有才尝试安装 Chromium
    from bili_common import find_local_browser
    if not find_local_browser():
        if not check_chromium():
            install_chromium()
    
    # 清除进度
    if reset and progress_file.exists():
        progress_file.unlink()
        log.info("已清除进度文件")
    
    all_videos = []
    
    with sync_playwright() as p:
        uid = get_uid(p, uid)
        
        mode = "manual" if is_manual else ("visible" if is_visible else "headless")
        log.info(f"启动浏览器（{mode} 模式）| UID: {uid}")
        
        context = create_browser_context(p, headless=not is_visible, uid=uid)
        page = context.pages[0] if context.pages else context.new_page()
        
        # 进入收藏夹页面
        favlist_url = f"https://space.bilibili.com/{uid}/favlist"
        log.info(f"进入收藏夹: {favlist_url}")
        page.goto(favlist_url, timeout=60_000)
        page.wait_for_timeout(2000)
        
        if "登录" in page.title():
            log.error("未登录，请删除 user_data 目录后重新运行")
            context.close()
            return []
        
        log.info("登录态验证通过")
        
        # 获取收藏夹列表
        favorites = fetch_favorites(page, uid)
        if not favorites:
            log.error("未获取到任何收藏夹")
            context.close()
            return []
        
        print_fav_list(favorites)
        
        # 筛选需要提取的收藏夹
        created_watch = [f for f in favorites if f.get("subtype") in ("created", "watch_later")]
        
        if fav_name:
            target = [f for f in favorites if f["name"] == fav_name]
            if not target:
                log.error(f"未找到名为「{fav_name}」的收藏夹")
                context.close()
                return []
            created_watch = target
        
        if not created_watch:
            log.warning("没有需要提取的收藏夹")
        else:
            print(f"\n{'=' * 62}")
            log.info(f"开始提取数据，共 {len(created_watch)} 个收藏夹")
            print(f"{'=' * 62}")
            
            total_videos = 0
            for idx, fav in enumerate(created_watch, 1):
                fav_name = fav["name"]
                safe_name = safe_filename(fav_name)
                progress_key = f"{uid}_{fav['id']}"
                
                # 断点续传检查
                if is_done(progress_file, progress_key) and not reset:
                    # 加载已有数据
                    json_path = data_dir / f"{safe_name}.json"
                    if json_path.exists():
                        existing = json.loads(json_path.read_text(encoding="utf-8"))
                        all_videos.extend(existing)
                        total_videos += len(existing)
                        log.info(f"[{idx}/{len(created_watch)}] ⏭️  跳过（已完成）: {fav_name} ({len(existing)} 个视频)")
                        continue
                
                print(f"\n{'─' * 50}")
                print(f"[{idx}/{len(created_watch)}] 📁 {fav_name}")
                print(f"{'─' * 50}")
                
                if is_manual:
                    print(f"  请在浏览器中手动点击「{fav_name}」")
                    print(f"  （或直接导航到 {build_fav_url(uid, fav)}）")
                    input("  ✅ 准备好后按 Enter 开始提取...")
                    page.wait_for_timeout(2000)
                else:
                    navigate_to_fav(page, uid, fav)
                
                # 滚动加载
                scroll_to_bottom(page, max_scrolls=MAX_SCROLLS)
                
                # 回到顶部
                page.evaluate("window.scrollTo(0, 0)")
                page.wait_for_timeout(500)
                
                # 提取数据（带重试）
                try:
                    videos = retry(lambda: extract_videos_from_page(page), max_retries=2)
                except Exception as e:
                    log.error(f"提取失败: {e}")
                    videos = []
                
                all_videos.extend(videos)
                total_videos += len(videos)
                
                # 保存 JSON
                json_path = data_dir / f"{safe_name}.json"
                with open(json_path, "w", encoding="utf-8") as f:
                    json.dump(videos, f, ensure_ascii=False, indent=2)
                
                # 标记完成
                mark_done(progress_file, progress_key)
                
                log.info(f"提取到 {len(videos)} 个视频 -> {json_path}")
                for v in videos[:3]:
                    log.info(f"  • {v['title'][:35]} | {v['author']} | {v['plays']}")
                if len(videos) > 3:
                    log.info(f"  ... 还有 {len(videos) - 3} 个")
        
        # 完成
        if not is_manual:
            context.close()
            log.info("浏览器已关闭")
        
        print(f"\n{'=' * 62}")
        log.info(f"全部完成！共 {total_videos} 个视频")
        log.info(f"数据目录: {data_dir.resolve()}")
        print(f"{'=' * 62}")
        
        if is_manual:
            print("\n💡 手动模式浏览器未关闭，检查完毕后手动关闭窗口即可")
    
    return all_videos


# ============================================================
# 🖥️ CLI 入口
# ============================================================


def main():
    parser = argparse.ArgumentParser(
        description="B站收藏夹数据提取工具",
        epilog="默认 headless 自动模式。加 --manual 可手动操作。",
    )
    parser.add_argument("--uid", type=str, help="指定 UID（不指定则使用默认 UID）")
    parser.add_argument("--visible", action="store_true", help="有头模式")
    parser.add_argument("--manual", action="store_true", help="手动模式")
    parser.add_argument("--reset", action="store_true", help="清除进度，重新提取")
    parser.add_argument("--fav", type=str, help="只提取指定收藏夹")
    args = parser.parse_args()
    
    collect_favorites(
        uid=args.uid,
        visible=args.visible,
        manual=args.manual,
        reset=args.reset,
        fav_name=args.fav,
    )


if __name__ == "__main__":
    main()
