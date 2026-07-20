#!/usr/bin/env python3
"""
B站数据 SQLite 存储模块

用法：
    import db
    conn = db.connect(uid)
    db.save_videos(conn, videos, favorite_name)
    all_videos = db.load_videos(uid)
"""

import json
import sqlite3
import time
import urllib.error
import urllib.request
from pathlib import Path

from bili_common import BILI_FAV_HOME


def db_path(uid: str) -> Path:
    """返回数据库文件路径: data_{uid}/bili.db"""
    return BILI_FAV_HOME / f"data_{uid}" / "bili.db"


def connect(uid: str) -> sqlite3.Connection:
    """连接（或创建）数据库，返回 conn"""
    path = db_path(uid)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    _migrate(conn)
    return conn


def _migrate(conn: sqlite3.Connection):
    """自动建表/迁移"""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS favorites (
            name    TEXT PRIMARY KEY,
            uid     TEXT NOT NULL,
            fav_id  INTEGER,
            media_count INTEGER DEFAULT 0,
            is_private  INTEGER DEFAULT 0,
            updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS videos (
            bvid    TEXT PRIMARY KEY,
            title   TEXT,
            author  TEXT,
            plays   TEXT,
            plays_num   REAL DEFAULT 0,
            danmaku TEXT,
            duration TEXT,
            link    TEXT,
            fav_time    INTEGER,
            favorite    TEXT,
            tags    TEXT DEFAULT '[]',
            updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_videos_favorite
        ON videos(favorite)
    """)
    conn.commit()


# ============================================================
# 收藏夹
# ============================================================


def save_favorite(conn: sqlite3.Connection, name: str, uid: str,
                  fav_id: int = 0, media_count: int = 0, is_private: bool = False):
    conn.execute("""
        INSERT OR REPLACE INTO favorites (name, uid, fav_id, media_count, is_private, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (name, uid, fav_id, media_count, int(is_private), int(time.time())))
    conn.commit()


# ============================================================
# 视频
# ============================================================


def save_video(conn: sqlite3.Connection, video: dict):
    """写入单个视频，bvid 重复时覆盖"""
    bvid = video.get("bvid", "")
    if not bvid:
        return
    plays_str = video.get("plays", "") or ""
    plays_num = _parse_plays(plays_str)
    tags = video.get("tags", [])
    if isinstance(tags, list):
        tags = json.dumps(tags, ensure_ascii=False)
    conn.execute("""
        INSERT OR REPLACE INTO videos
            (bvid, title, author, plays, plays_num, danmaku, duration,
             link, fav_time, favorite, tags, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        bvid,
        video.get("title", ""),
        video.get("author", ""),
        plays_str,
        plays_num,
        video.get("danmaku", ""),
        video.get("duration", ""),
        video.get("link", ""),
        video.get("fav_time"),
        video.get("_favorite", video.get("favorite", "")),
        tags,
        int(time.time()),
    ))
    conn.commit()


def save_videos(conn: sqlite3.Connection, videos: list[dict]):
    """批量写入视频"""
    for v in videos:
        save_video(conn, v)


def update_tags(conn: sqlite3.Connection, bvid: str, tags: list[str]):
    """更新视频标签"""
    conn.execute(
        "UPDATE videos SET tags=?, updated_at=? WHERE bvid=?",
        (json.dumps(tags, ensure_ascii=False), int(time.time()), bvid),
    )
    conn.commit()


def load_videos(uid: str, favorite: str = None) -> list[dict]:
    """读取视频列表，返回 list[dict]"""
    conn = connect(uid)
    if favorite:
        rows = conn.execute(
            "SELECT * FROM videos WHERE favorite=? ORDER BY fav_time DESC", (favorite,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM videos ORDER BY favorite, fav_time DESC").fetchall()
    cols = [d[1] for d in conn.execute("PRAGMA table_info(videos)").fetchall()]
    conn.close()
    result = []
    for row in rows:
        d = dict(zip(cols, row))
        if d.get("tags"):
            try:
                d["tags"] = json.loads(d["tags"])
            except (json.JSONDecodeError, TypeError):
                d["tags"] = []
        result.append(d)
    return result


def get_all_bvids(uid: str) -> set[str]:
    """获取数据库中所有 bvid"""
    conn = connect(uid)
    rows = conn.execute("SELECT bvid FROM videos").fetchall()
    conn.close()
    return {r[0] for r in rows}


def get_videos_without_tags(uid: str) -> list[dict]:
    """获取 tags 为空的视频"""
    conn = connect(uid)
    rows = conn.execute(
        "SELECT bvid, title FROM videos WHERE tags='[]' OR tags IS NULL"
    ).fetchall()
    conn.close()
    return [{"bvid": r[0], "title": r[1]} for r in rows]


# ============================================================
#  工具
# ============================================================


def _parse_plays(plays_str: str) -> float:
    """"623.8万" → 6238000, "1705" → 1705, "" → 0"""
    if not plays_str or not isinstance(plays_str, str):
        return 0.0
    s = plays_str.strip()
    multiplier = 10000 if "万" in s else (100000000 if "亿" in s else 1)
    s = s.replace("亿", "").replace("万", "").replace(",", "")
    try:
        return float(s) * multiplier
    except ValueError:
        return 0.0


# 有 B站社区含义的 emoji，计数时当作有效文字处理
_KNOWN_EMOJI = {"🍬"}  # 🍬 = 唐/千早爱音/MyGO 系列


def _title_is_cryptic(title: str) -> bool:
    """判断标题是否无法提取有意义的信息"""
    if not title or len(title.strip()) < 3:
        return True
    meaningful = 0
    special = 0
    for ch in title:
        if ch in _KNOWN_EMOJI:
            meaningful += 1  # 白名单emoji算有效字符
        elif '一' <= ch <= '鿿' or ch.isalnum():
            meaningful += 1
        elif ord(ch) > 0x2000:  # emoji / 特殊符号区域
            special += 1
    if meaningful >= 3:
        return False
    total = len(title.strip())
    if total > 0 and special / total > 0.4:
        return True
    return True  # 默认保守标记为cryptic


def fetch_missing_tags(uid: str, delay: float = 0.5) -> int:
    """对标题无意义的视频，回退调 B站 API 获取标签。

    1. 遍历 tags 为空的视频
    2. 标题有意义 → 标记为 __title_sufficient__（跳过）
    3. 标题无意义 → 调 API 取标签 → 写入 DB

    Returns: 实际调用了 API 的视频数
    """
    videos = get_videos_without_tags(uid)
    if not videos:
        print(f"  无需处理（所有视频已有标签）")
        return 0

    cryptic_count = sum(1 for v in videos if _title_is_cryptic(v.get("title", "")))
    print(f"  检查 {len(videos)} 个视频，其中 {cryptic_count} 个需要 API 回退...")

    conn = connect(uid)
    api_calls = 0
    for v in videos:
        bvid = v.get("bvid", "")
        title = v.get("title", "")
        if not bvid:
            continue

        if not _title_is_cryptic(title):
            # 标题信息足够，标记跳过
            update_tags(conn, bvid, ["__title_sufficient__"])
            continue

        # 标题无意义 → 调 API
        try:
            url = f"https://api.bilibili.com/x/tag/archive/tags?bvid={bvid}"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36", "Referer": "https://www.bilibili.com/"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            if data.get("code") == 0 and data.get("data"):
                tags = [t["tag_name"] for t in data["data"] if t.get("tag_name")]
                if tags:
                    update_tags(conn, bvid, tags)
                    print(f"    ✓ {title[:20]:20s} → {tags[:3]}{'...' if len(tags)>3 else ''}")
                    api_calls += 1
                    time.sleep(delay)
                    continue
            update_tags(conn, bvid, ["__api_empty__"])
            print(f"    - {title[:20]:20s} → API 无返回")
        except Exception as e:
            update_tags(conn, bvid, ["__api_failed__"])
            print(f"    ✗ {title[:20]:20s} → {e}")

    conn.close()
    print(f"  API 调用: {api_calls} 次")
    return api_calls


# ============================================================
#  CLI 入口
# ============================================================


def cmd_fetch_tags():
    """CLI: --fetch-tags"""
    uid = ""
    if len(sys.argv) > 2 and not sys.argv[2].startswith("-"):
        uid = sys.argv[2]
    else:
        # 尝试从 UID_FILE 读取
        uid_file = Path(__file__).parent / "bili_uid.txt"
        if uid_file.exists():
            uid = uid_file.read_text().strip()
    if not uid:
        print("用法: python db.py --fetch-tags [uid]")
        print("      (或在项目目录运行，自动读取 bili_uid.txt)")
        return
    fetch_missing_tags(uid)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--fetch-tags":
        cmd_fetch_tags()
    else:
        print("用法: python db.py --fetch-tags [uid]")
