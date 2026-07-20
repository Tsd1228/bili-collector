#!/usr/bin/env python3
"""
B站工具库 — 共享模块

提供：
  - 登录 & UID 管理
  - 收藏夹列表获取
  - URL 构建
  - Chromium 检查/安装
  - 滚动加载
  - 日志工具
"""

import json
import logging
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

# ============================================================
# 路径常量
# ============================================================

# 数据目录：默认在脚本/exe 同级目录下（便携模式）
# 如果需要存到用户目录，设环境变量 BILI_PORTABLE=0
_base_dir = Path(__file__).parent.resolve()
if os.environ.get("BILI_PORTABLE", "1") == "0":
    _base_dir = Path.home() / ".bilibili_fav"

BILI_FAV_HOME = _base_dir
UID_FILE = BILI_FAV_HOME / "bili_uid.txt"


def get_user_dir(uid: str = None) -> Path:
    """按 UID 隔离的浏览器数据目录"""
    if uid:
        return BILI_FAV_HOME / f"user_data_{uid}"
    return BILI_FAV_HOME / "user_data"


def get_data_dir(uid: str = None) -> Path:
    """按 UID 隔离的输出数据目录"""
    if uid:
        return BILI_FAV_HOME / f"data_{uid}"
    return BILI_FAV_HOME / "data"


def get_progress_file(uid: str = None) -> Path:
    """按 UID 隔离的进度文件"""
    data_dir = get_data_dir(uid)
    return data_dir / ".progress.json"

# ============================================================
# 日志
# ============================================================

_logger = None


def get_logger(name: str = "bili") -> logging.Logger:
    global _logger
    if _logger is None:
        _logger = logging.getLogger(name)
        _logger.setLevel(logging.DEBUG)
        if not _logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter(
                "%(asctime)s [%(levelname)s] %(message)s",
                datefmt="%H:%M:%S",
            ))
            _logger.addHandler(handler)
    return _logger


log = get_logger()

# ============================================================
# 基础工具
# ============================================================


def ensure_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True)


def safe_filename(name: str) -> str:
    """将字符串转为安全文件名"""
    name = re.sub(r'[\\/:*?"<>|]', "_", name).strip()
    return name or "unnamed"


def retry(fn, max_retries: int = 3, delay: float = 2.0, backoff: float = 2.0):
    """带指数退避的重试装饰器"""
    last_err = None
    for attempt in range(max_retries):
        try:
            return fn()
        except Exception as e:
            last_err = e
            if attempt < max_retries - 1:
                wait = delay * (backoff ** attempt)
                log.warning(f"重试 {attempt + 1}/{max_retries}，等待 {wait:.1f}s: {e}")
                time.sleep(wait)
    raise last_err


# ============================================================
# Chromium 检查/安装
# ============================================================


def check_chromium() -> bool:
    from playwright._impl._driver import compute_driver_executable
    from playwright._impl._driver import get_driver_env

    try:
        driver_executable = compute_driver_executable()
        driver_env = get_driver_env()
        result = subprocess.run(
            [str(driver_executable), "print-drv"],
            env=driver_env,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except Exception:
        return False


def install_chromium():
    log.info("Downloading Chromium...")

    import subprocess
    import os

    # Find the playwright driver
    try:
        from playwright._impl._driver import compute_driver_executable, get_driver_env
        driver_executable = compute_driver_executable()
        driver_env = get_driver_env()
    except Exception as e:
        log.error(f"Cannot find playwright driver: {e}")
        raise

    # 国内镜像
    mirror = "https://npmmirror.com/mirrors/playwright"
    driver_env["PLAYWRIGHT_DOWNLOAD_HOST"] = mirror
    log.info(f"Using mirror: {mirror}")

    # Try install with retries
    for attempt in range(3):
        try:
            log.info(f"Attempt {attempt + 1}/3...")
            result = subprocess.run(
                [str(driver_executable), "install", "chromium"],
                env=driver_env,
                capture_output=True,
                text=True,
                timeout=300,
            )
            if result.returncode == 0:
                log.info("Chromium installed")
                return
            else:
                log.warning(f"Install returned code {result.returncode}: {result.stderr[:200]}")
        except subprocess.TimeoutExpired:
            log.warning(f"Attempt {attempt + 1} timed out")
        except Exception as e:
            log.warning(f"Attempt {attempt + 1} failed: {e}")

    raise RuntimeError("Failed to install Chromium after 3 attempts")


# ============================================================
# 登录 & UID
# ============================================================


def do_login(p, uid: str = None) -> str:
    """执行扫码登录，返回 UID。
    
    如果指定 uid，则使用该 uid 对应的 user_data 目录。
    否则登录后自动获取 UID 并创建对应的 user_data 目录。
    """
    # 确定要登录的 UID
    target_uid = uid
    
    if not target_uid:
        # 先检查是否有保存的 UID
        if UID_FILE.exists():
            target_uid = UID_FILE.read_text().strip()
    
    if not target_uid:
        # 需要扫码登录，先用临时目录获取 UID
        log.info("启动有头浏览器登录（临时上下文）...")
        temp_user_dir = get_user_dir("temp")
        temp_user_dir.mkdir(parents=True, exist_ok=True)
        
        launch_kwargs = {
            "user_data_dir": str(temp_user_dir),
            "headless": False,
            "args": ["--no-sandbox"],
            "viewport": {"width": 1080, "height": 1080},
        }
        
        local_browser = find_local_browser()
        if local_browser:
            launch_kwargs["executable_path"] = local_browser
        
        context = p.chromium.launch_persistent_context(**launch_kwargs)
        
        page = context.pages[0] if context.pages else context.new_page()
        
        print("打开 B站 首页")
        page.goto("https://www.bilibili.com", timeout=30_000)
        page.wait_for_timeout(3000)
        
        print("⏳ 请扫码登录...")
        while page.locator(".bili-avatar").count() == 0:
            page.wait_for_timeout(3000)
        
        print("  登录成功")
        
        target_uid = page.evaluate("""
            () => {
                if (window.__INITIAL_STATE__?.userInfo?.mid) {
                    return String(window.__INITIAL_STATE__.userInfo.mid);
                }
                const m = document.cookie.match(/DedeUserID=(\\d+)/);
                if (m) return m[1];
                return null;
            }
        """)
        
        if not target_uid:
            raise RuntimeError("无法获取 UID")
        
        target_uid = target_uid.strip()
        context.close()
        
        # 将临时目录重命名为正式的 UID 目录
        final_user_dir = get_user_dir(target_uid)
        if final_user_dir.exists():
            import shutil
            shutil.rmtree(str(final_user_dir))
        temp_user_dir.rename(final_user_dir)
        
        # 保存 UID
        UID_FILE.write_text(target_uid)
        log.info(f"UID: {target_uid}")
        print("登录浏览器已关闭")
    
    return target_uid


def get_uid(p, uid: str = None) -> str:
    """获取 UID。如果指定 uid 则直接返回，否则按默认逻辑获取。"""
    if uid:
        return uid
    if UID_FILE.exists():
        uid = UID_FILE.read_text().strip()
        log.info(f"检测到 UID: {uid}")
        return uid
    return do_login(p)


# ============================================================
# 收藏夹 API
# ============================================================


def build_fav_url(uid: str, fav: dict) -> str:
    """构造收藏夹页面 URL"""
    st = fav.get("subtype", fav.get("type", "created"))
    if st in ("created", "watch_later"):
        return f"https://space.bilibili.com/{uid}/favlist?fid={fav['id']}&ftype=create"
    return f"https://space.bilibili.com/{uid}/favlist?fid={fav['id']}&ftype=collect&ctype=21"


def is_folder_private(fav: dict) -> bool:
    """判断收藏夹是否私密（通过 attr 字段的 bit 0）"""
    return bool(fav.get("attr", 0) & 1)


def fetch_favorites(page, uid: str) -> list[dict]:
    """通过 API 获取用户全部收藏夹"""
    log.info("获取收藏夹列表...")
    all_favs = []

    # 创建的收藏夹
    created = page.evaluate("""
        async (uid) => {
            try {
                const resp = await fetch(
                    `https://api.bilibili.com/x/v3/fav/folder/created/list`
                    + `?up_mid=${uid}&ps=50&pn=1&web_location=333.1387`,
                    { credentials: "include" }
                );
                const data = await resp.json();
                if (data.code === 0 && data.data && data.data.list) {
                    return data.data.list.map(f => ({
                        id: f.id,
                        name: f.title,
                        media_count: f.media_count,
                        attr: f.attr || 0,
                        type: "created",
                        subtype: f.id === 0 ? "watch_later" : "created",
                    }));
                }
                return { error: data.message || "created API error" };
            } catch (e) {
                return { error: e.message };
            }
        }
    """, uid)

    if isinstance(created, list):
        log.info(f"创建的收藏夹: {len(created)} 个")
        all_favs.extend(created)
    else:
        log.error(f"获取创建的收藏夹失败: {created.get('error')}")

    # 收藏的收藏夹（翻页）
    collected_all = []
    pn = 1
    while True:
        result = page.evaluate("""
            async (args) => {
                const [uid, pageNum] = args;
                try {
                    const resp = await fetch(
                        `https://api.bilibili.com/x/v3/fav/folder/collected/list`
                        + `?up_mid=${uid}&pn=${pageNum}&ps=50&platform=web&web_location=333.1387`,
                        { credentials: "include" }
                    );
                    const data = await resp.json();
                    if (data.code === 0 && data.data) {
                        return {
                            list: (data.data.list || []).map(f => ({
                                id: f.id,
                                name: f.title,
                                media_count: f.media_count,
                                attr: f.attr || 0,
                                type: "collected",
                                subtype: f.type === 1 ? "followed" : "other",
                            })),
                            total: data.data.total || 0,
                            has_more: data.data.has_more || 0,
                        };
                    }
                    return { error: data.message || "collected API error" };
                } catch (e) {
                    return { error: e.message };
                }
            }
        """, [uid, pn])

        if isinstance(result, dict) and "error" in result:
            log.error(f"获取收藏的收藏夹失败: {result.get('error')}")
            break

        if result.get("list"):
            collected_all.extend(result["list"])
            log.debug(f"第 {pn} 页: {len(result['list'])} 个")
            if result.get("has_more"):
                pn += 1
                page.wait_for_timeout(500)
            else:
                break
        else:
            break

    if collected_all:
        all_favs.extend(collected_all)
        followed = sum(1 for f in collected_all if f["subtype"] == "followed")
        other = sum(1 for f in collected_all if f["subtype"] == "other")
        log.info(f"收藏的收藏夹: {len(collected_all)} 个 (追的合集: {followed}, 其他: {other})")

    return all_favs


# ============================================================
# 点赞视频 API
# ============================================================


def fetch_liked_videos(page, uid: str) -> list[dict]:
    """获取用户最近点赞的视频列表（最多 20 条）。"""
    result = page.evaluate("""
        async (uid) => {
            try {
                const resp = await fetch(
                    `https://api.bilibili.com/x/space/like/video?vmid=${uid}`,
                    { credentials: "include" }
                );
                const data = await resp.json();
                if (data.code === 0 && data.data) {
                    return (data.data.list || []).map(v => ({
                        bvid: v.bvid,
                        title: v.title,
                        author: v.author,
                        plays: v.play,
                        pic: v.pic || "",
                    }));
                }
                return { error: data.message || "liked API error" };
            } catch (e) {
                return { error: e.message };
            }
        }
    """, uid)

    if isinstance(result, list):
        log.info(f"点赞视频: {len(result)} 条")
        return result
    else:
        log.warning(f"获取点赞视频失败: {result.get('error')}")
        return []


def print_fav_list(favorites: list[dict], show_all: bool = True):
    """打印收藏夹清单"""
    created_watch = [f for f in favorites if f.get("subtype") in ("created", "watch_later")]
    followed = [f for f in favorites if f.get("subtype") == "followed"]
    other = [f for f in favorites if f.get("subtype") == "other"]

    print("\n" + "=" * 62)
    print("   收藏夹清单")
    print("=" * 62)

    if created_watch:
        print(f"\n自建收藏夹 ({len(created_watch)} 个):")
        for f in created_watch:
            tag = "[稍后再看]" if f["subtype"] == "watch_later" else "[自建]"
            print(f"  {tag} {f['name']}  ({f.get('media_count', '?')} 个内容)")

    if followed and show_all:
        print(f"\n收藏的合集 ({len(followed)} 个):")
        for f in followed:
            print(f"  {f['name']}  ({f.get('media_count', '?')} 个内容)")

    if other and show_all:
        print(f"\n其他收藏 ({len(other)} 个):")
        for f in other:
            print(f"  {f['name']}  ({f.get('media_count', '?')} 个内容)")


# ============================================================
# 滚动加载
# ============================================================


def scroll_to_bottom(page, max_scrolls: int = 30, step: int = 800) -> int:
    """滚动页面加载全部内容，返回滚动次数"""
    log.info("滚动加载内容...")
    last_height = 0
    stall_count = 0
    scroll_count = 0

    for i in range(max_scrolls):
        page.mouse.wheel(0, step)
        page.wait_for_timeout(400)
        scroll_count += 1

        current_height = page.evaluate("document.body.scrollHeight")
        if current_height == last_height:
            stall_count += 1
            if stall_count >= 3:
                log.info(f"内容已全部加载（第 {i + 1} 次滚动后稳定）")
                break
        else:
            stall_count = 0
        last_height = current_height

        if (i + 1) % 10 == 0:
            log.info(f"已滚动 {i + 1} 次...")

    return scroll_count


# ============================================================
#  断点续传
# ============================================================


def load_progress(progress_file: Path) -> dict:
    """加载进度文件"""
    if progress_file.exists():
        try:
            return json.loads(progress_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_progress(progress_file: Path, data: dict):
    """保存进度文件"""
    progress_file.parent.mkdir(parents=True, exist_ok=True)
    progress_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def mark_done(progress_file: Path, key: str):
    """标记某项已完成"""
    progress = load_progress(progress_file)
    progress[key] = {"done": True, "time": datetime.now().isoformat()}
    save_progress(progress_file, progress)


def is_done(progress_file: Path, key: str) -> bool:
    """检查某项是否已完成"""
    progress = load_progress(progress_file)
    return progress.get(key, {}).get("done", False)


# ============================================================
# 浏览器启动
# ============================================================


def find_local_browser() -> str | None:
    """查找本地 Chrome 或 Edge 浏览器路径"""
    import platform
    system = platform.system()

    if system == "Windows":
        candidates = [
            # Chrome
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            # Edge
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        ]
    elif system == "Darwin":
        candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        ]
    else:
        candidates = [
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
            "/usr/bin/chromium",
            "/usr/bin/chromium-browser",
            "/usr/bin/microsoft-edge",
        ]

    for path in candidates:
        if os.path.exists(path):
            log.info(f"Found browser: {path}")
            return path

    return None


def create_browser_context(p, headless: bool = True, uid: str = None):
    """创建浏览器上下文，优先使用本地浏览器"""
    import os
    user_dir = get_user_dir(uid)
    user_dir.mkdir(parents=True, exist_ok=True)

    kwargs = {
        "user_data_dir": str(user_dir),
        "headless": headless,
        "args": ["--no-sandbox"],
        "viewport": {"width": 1080, "height": 1080},
    }

    # 优先使用本地浏览器，跳过 Chromium 下载
    local_browser = find_local_browser()
    if local_browser:
        kwargs["executable_path"] = local_browser
        log.info(f"Using local browser: {local_browser}")

    return p.chromium.launch_persistent_context(**kwargs)


def navigate_to_fav(page, uid: str, fav: dict) -> bool:
    """导航到指定收藏夹，返回是否成功"""
    url = build_fav_url(uid, fav)
    log.info(f"导航到: {url}")
    page.goto(url, timeout=60_000)
    page.wait_for_timeout(4000)

    # 处理弹窗
    try:
        page.click("text=我知道了", timeout=2000)
        page.wait_for_timeout(1000)
    except Exception:
        pass

    if f"fid={fav['id']}" in page.url:
        return True

    log.warning(f"URL 不匹配: {page.url}")
    return False
