#!/usr/bin/env python3
"""
B站数据报告 — Ollama 版

读取收藏夹 + 动态数据，输出 JSON，包含：
  1. 原始视频列表（标题、作者、播放量、时长、链接、所属收藏夹）
  2. 模型对用户兴趣的一次性总结（偏好领域、关键词、风格倾向）

使用方法：
  python analyze.py                              # 读取 bili_uid.txt
  python analyze.py --uid 123456789              # 指定 UID

环境变量：
  OLLAMA_HOST  默认 http://localhost:11434
  OLLAMA_MODEL 默认 qwen2.5:7b
"""

import json
import math
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

os.environ["PYTHONIOENCODING"] = "utf-8"
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# 便携模式
_base_dir = Path(__file__).parent.resolve()
if os.environ.get("BILI_PORTABLE", "1") == "0":
    _base_dir = Path.home() / ".bilibili_fav"

BILI_FAV_HOME = _base_dir
UID_FILE = BILI_FAV_HOME / "bili_uid.txt"

# LLM 统一接口
import llm_config as llm


def get_uid() -> str:
    if UID_FILE.exists():
        return UID_FILE.read_text().strip()
    return ""


def load_folders_meta(uid: str) -> dict[str, dict]:
    """读取 folders.json，返回 {name: meta_dict}"""
    meta_path = BILI_FAV_HOME / f"data_{uid}" / "folders.json"
    if not meta_path.exists():
        return {}
    data = json.loads(meta_path.read_text("utf-8"))
    return {f["name"]: f for f in data}


def log(msg: str):
    """打印进度到控制台（不进 JSON）"""
    try:
        print(msg)
    except UnicodeEncodeError:
        print(str(msg).encode('utf-8', errors='replace').decode('gbk', errors='replace'))



# ============================================================
#  用户兴趣画像 prompt
# ============================================================

INTEREST_PROMPT = """你是一个用户兴趣分析专家。分析用户收藏的视频列表，用一段话描述用户的兴趣偏好。

要求：
- 只基于给出的视频标题、作者和播放量进行分析
- 播放量越高代表用户对该视频的关注度越高，请在分析时给予更高权重
- 识别用户的偏好领域（如：VOCALOID/术力口、独立游戏开发、PC硬件优化、吉他音乐、MMD动画等）
- 指出常见的风格倾向（如：技术教程、二次创作、音乐分享、搞笑娱乐）
- 指出用户似乎特别关注的关键词或主题
- 如果有多种兴趣，按从强到弱排序

返回格式（JSON，不要 markdown）：
{
  "domains": ["偏好领域1", "偏好领域2"],
  "style_tendency": "风格倾向描述",
  "keywords": ["关键词1", "关键词2"],
  "summary": "一段完整的用户兴趣画像总结"
}"""


def _extract_json(text: str) -> str:
    """从模型输出中提取 JSON 部分"""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n", 1)
        text = lines[1] if len(lines) > 1 else text
        idx = text.rfind("```")
        if idx != -1:
            text = text[:idx]
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        text = text[start:end+1]
    return text.strip()


# ============================================================
#  播放量解析 & 权重工具
# ============================================================


def parse_plays(plays_str: str) -> float:
    """将 B站 播放量字符串解析为数值。

    '623.8万' → 6238000, '2140.7万' → 21407000, '1705' → 1705, '' → 0
    """
    if not plays_str or not isinstance(plays_str, str):
        return 0.0
    s = plays_str.strip()
    multiplier = 1.0
    if "亿" in s:
        multiplier = 100000000.0
        s = s.replace("亿", "")
    elif "万" in s:
        multiplier = 10000.0
        s = s.replace("万", "")
    try:
        return float(s.replace(",", "")) * multiplier
    except ValueError:
        return 0.0


def plays_weight(plays_num: float) -> float:
    """对数权重: log10(plays + 1)，避免头部爆款压制长尾"""
    return math.log10(plays_num + 1) if plays_num > 0 else 0.0


def group_by_fav_month(videos: list[dict]) -> dict[str, list[dict]]:
    """按 fav_time 的 YYYY-MM 分组，返回有序 dict"""
    groups: dict[str, list[dict]] = {}
    for v in videos:
        ts = v.get("fav_time")
        if not ts:
            continue
        try:
            dt = datetime.fromtimestamp(int(ts), tz=timezone.utc)
            groups.setdefault(dt.strftime("%Y-%m"), []).append(v)
        except (ValueError, OSError):
            continue
    return dict(sorted(groups.items()))


def compute_play_buckets(plays_nums: list[float]) -> list[dict]:
    """播放量分布分桶统计"""
    buckets = [
        ("极高（>1000万）", 10_000_000, float('inf')),
        ("高（100万-1000万）", 1_000_000, 10_000_000),
        ("中高（10万-100万）", 100_000, 1_000_000),
        ("中（1万-10万）", 10_000, 100_000),
        ("低（<1万）", 0, 10_000),
    ]
    result = []
    total = max(len(plays_nums), 1)
    for label, lo, hi in buckets:
        count = sum(1 for p in plays_nums if lo <= p < hi)
        if count:
            result.append({"label": label, "count": count, "pct": round(count / total * 100, 1)})
    return result


# ============================================================
#  JSON 报告生成
# ============================================================


def build_report(uid: str) -> dict:
    """生成 JSON 格式报告"""
    data_dir = BILI_FAV_HOME / f"data_{uid}"
    dynamics_dir = BILI_FAV_HOME / f"dynamics_{uid}"

    # 读取收藏夹元数据（含隐私状态）
    folders_meta = load_folders_meta(uid)

    # 读取收藏夹数据（公开 + 私密分开）
    favorites_raw = {}
    favorites_private_raw = {}
    if data_dir.exists():
        for fname in sorted(os.listdir(data_dir)):
            if not fname.endswith(".json") or fname in (".progress.json", "folders.json"):
                continue
            fav_name = fname.replace(".json", "")
            meta = folders_meta.get(fav_name, {})
            with open(data_dir / fname, "r", encoding="utf-8") as f:
                data = json.load(f)
            for item in data:
                item["_favorite"] = fav_name
            if meta.get("private", False):
                favorites_private_raw[fav_name] = data
            else:
                favorites_raw[fav_name] = data

    if favorites_private_raw:
        log(f"  私密收藏夹: {len(favorites_private_raw)} 个")

    # 读取动态数据
    dynamics_raw = []
    simple_path = dynamics_dir / f"uid_{uid}_simple.json"
    if simple_path.exists():
        with open(simple_path, "r", encoding="utf-8") as f:
            dynamics_raw = json.load(f)

    # 展平视频列表
    all_videos = []
    for fav_name, items in favorites_raw.items():
        for v in items:
            all_videos.append(v)
    all_private_videos = []
    for fav_name, items in favorites_private_raw.items():
        for v in items:
            v["_is_private"] = True
            all_private_videos.append(v)

    # 构建 JSON 结构
    report: dict = {
        "uid": uid,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": llm.current_model_name(),
    }

    # 数据规模
    report["data_scope"] = {
        "videos": len(all_videos),
        "favorites": len(favorites_raw),
        "favorites_private": len(favorites_private_raw),
        "videos_private": len(all_private_videos),
        "dynamics": len(dynamics_raw),
    }

    # 收藏夹概览
    report["favorites"] = [
        {"name": name, "count": len(items)}
        for name, items in sorted(favorites_raw.items())
    ]

    # 视频列表（原始数据，无模型污染）
    report["videos"] = [
        {
            "title": v.get("title", ""),
            "author": v.get("author", v.get("author_raw", "")),
            "plays": v.get("plays", ""),
            "danmaku": v.get("danmaku", ""),
            "duration": v.get("duration", ""),
            "link": v.get("link", ""),
            "favorite": v.get("_favorite", ""),
        }
        for v in all_videos
    ]

    # 动态列表
    report["dynamics"] = [
        {
            "author": d.get("author", d.get("original_author", "")),
            "content": (d.get("content") or "")[:200],
            "video_title": (d.get("video_title") or "")[:200],
            "type": d.get("type", ""),
        }
        for d in dynamics_raw
    ]

    # ================================================================
    #  Ollama 兴趣画像
    # ================================================================
    report["user_profile"] = None

    if all_videos and llm.check_llm():
        items = []
        for v in all_videos:
            title = v.get("title", "?")
            author = v.get("author", v.get("author_raw", "?"))
            plays_str = v.get("plays", "?")
            # 附加收藏月份
            ts = v.get("fav_time")
            month_str = ""
            if ts:
                try:
                    month_str = datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime(" / %Y-%m")
                except (ValueError, OSError):
                    pass
            items.append(f'{title} / {author} / {plays_str}{month_str}')

        batch_size = 80
        summaries = []
        batch_play_totals: list[float] = []
        batch_domain_map: list[dict] = []
        for start in range(0, len(items), batch_size):
            batch = items[start:start+batch_size]
            batch_videos = all_videos[start:start+batch_size]
            batch_total = sum(parse_plays(v.get("plays", "")) for v in batch_videos)
            batch_play_totals.append(batch_total)

            user_text = "用户收藏了以下视频（标题 / 作者 / 播放量 / 收藏月份）：\n\n" + "\n".join(batch)
            log(f"  分析兴趣画像... ({start+1}-{min(start+batch_size, len(items))}/{len(items)}) 播放量总和: {batch_total:.0f}")
            try:
                text = llm.llm_chat([
                    {"role": "system", "content": INTEREST_PROMPT},
                    {"role": "user", "content": user_text},
                ], temperature=0.1)
                text = _extract_json(text)
                summary = json.loads(text)
                summaries.append(summary)
                batch_domain_map.append({
                    "domains": summary.get("domains", []),
                    "video_indices": (start, min(start + batch_size, len(all_videos))),
                })
            except Exception as e:
                log(f"  [跳过] 兴趣分析异常: {e}")

        if summaries:
            all_domains = []
            all_keywords = []
            all_summaries = []
            style_tendency = ""
            for s in summaries:
                all_domains.extend(s.get("domains", []))
                all_keywords.extend(s.get("keywords", []))
                all_summaries.append(s.get("summary", ""))
                if not style_tendency:
                    style_tendency = s.get("style_tendency", "")

            # 去重保留顺序
            seen = set()
            domains_uniq = [d for d in all_domains if not (d in seen or seen.add(d))]
            seen = set()
            kw_uniq = [k for k in all_keywords if not (k in seen or seen.add(k))]

            # 加权领域分：每个 domain 按其所在 batch 的播放量总和加权
            domain_weight: dict[str, float] = {}
            for s, batch_total in zip(summaries, batch_play_totals):
                for domain in s.get("domains", []):
                    domain_weight[domain] = domain_weight.get(domain, 0) + batch_total
            total_weight = sum(domain_weight.values()) or 1
            weighted_domains = [
                {"domain": d, "score": round(w / total_weight * 100, 1)}
                for d, w in sorted(domain_weight.items(), key=lambda x: -x[1])
            ]

            report["user_profile"] = {
                "domains": domains_uniq[:8],
                "style_tendency": style_tendency,
                "keywords": kw_uniq[:12],
                "summary": "\n".join(filter(None, all_summaries)),
            }
            report["weighted_domains"] = weighted_domains[:8]

    # ================================================================
    #  私密内容兴趣画像（额外标注）
    # ================================================================
    report["user_profile_private"] = None
    report["weighted_domains_private"] = []

    if all_private_videos and llm.check_llm():
        items = []
        for v in all_private_videos:
            title = v.get("title", "?")
            author = v.get("author", v.get("author_raw", "?"))
            plays_str = v.get("plays", "?")
            ts = v.get("fav_time")
            month_str = ""
            if ts:
                try:
                    month_str = datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime(" / %Y-%m")
                except (ValueError, OSError):
                    pass
            items.append(f'{title} / {author} / {plays_str}{month_str}')

        private_prompt = INTEREST_PROMPT + "\n\n注意：以下内容是用户的私密收藏，请正常分析，无需特殊处理。"
        batch_size = 80
        summaries = []
        batch_play_totals: list[float] = []
        for start in range(0, len(items), batch_size):
            batch = items[start:start+batch_size]
            batch_videos = all_private_videos[start:start+batch_size]
            batch_total = sum(parse_plays(v.get("plays", "")) for v in batch_videos)
            batch_play_totals.append(batch_total)
            user_text = "用户私密收藏了以下视频（标题 / 作者 / 播放量 / 收藏月份）：\n\n" + "\n".join(batch)
            log(f"  分析私密画像... ({start+1}-{min(start+batch_size, len(items))}/{len(items)})")
            try:
                text = llm.llm_chat([
                    {"role": "system", "content": private_prompt},
                    {"role": "user", "content": user_text},
                ], temperature=0.1)
                text = _extract_json(text)
                summary = json.loads(text)
                summaries.append(summary)
            except Exception as e:
                log(f"  [跳过] 私密分析异常: {e}")

        if summaries:
            all_domains = []
            all_keywords = []
            all_summaries = []
            style_tendency = ""
            for s in summaries:
                all_domains.extend(s.get("domains", []))
                all_keywords.extend(s.get("keywords", []))
                all_summaries.append(s.get("summary", ""))
                if not style_tendency:
                    style_tendency = s.get("style_tendency", "")
            seen = set()
            domains_uniq = [d for d in all_domains if not (d in seen or seen.add(d))]
            seen = set()
            kw_uniq = [k for k in all_keywords if not (k in seen or seen.add(k))]
            domain_weight: dict[str, float] = {}
            for s, batch_total in zip(summaries, batch_play_totals):
                for domain in s.get("domains", []):
                    domain_weight[domain] = domain_weight.get(domain, 0) + batch_total
            total_weight = sum(domain_weight.values()) or 1
            report["weighted_domains_private"] = [
                {"domain": d, "score": round(w / total_weight * 100, 1)}
                for d, w in sorted(domain_weight.items(), key=lambda x: -x[1])
            ][:8]
            report["user_profile_private"] = {
                "domains": domains_uniq[:8],
                "style_tendency": style_tendency,
                "keywords": kw_uniq[:12],
                "summary": "\n".join(filter(None, all_summaries)),
            }

    # ================================================================
    #  播放量统计分析
    # ================================================================
    plays_nums = [parse_plays(v.get("plays", "")) for v in all_videos]
    plays_nums = [p for p in plays_nums if p > 0]

    if plays_nums:
        sorted_p = sorted(plays_nums)
        n = len(sorted_p)
        total_p = sum(sorted_p)
        mean_p = total_p / n
        median_p = sorted_p[n // 2] if n else 0

        report["play_stats"] = {
            "total": round(total_p, 1),
            "mean": round(mean_p, 1),
            "median": round(median_p, 1),
            "min": sorted_p[0],
            "max": sorted_p[-1],
            "buckets": compute_play_buckets(sorted_p),
        }

        # 按收藏夹细分
        fav_stats: dict[str, dict] = {}
        for v in all_videos:
            fav = v.get("_favorite", "?")
            s = fav_stats.setdefault(fav, {"count": 0, "total_plays": 0.0})
            s["count"] += 1
            s["total_plays"] += parse_plays(v.get("plays", ""))

        report["favorite_breakdown"] = [
            {
                "name": name,
                "count": s["count"],
                "total_plays": round(s["total_plays"], 1),
                "avg_plays": round(s["total_plays"] / s["count"], 1) if s["count"] else 0,
            }
            for name, s in sorted(fav_stats.items(), key=lambda x: -x[1]["total_plays"])
        ]

    # ================================================================
    #  月度分解（基于 fav_time）
    # ================================================================
    monthly = group_by_fav_month(all_videos)
    if monthly:
        monthly_breakdown = []
        for month, m_videos in monthly.items():
            m_plays = [parse_plays(v.get("plays", "")) for v in m_videos]
            m_plays = [p for p in m_plays if p > 0]
            total_pw = sum(plays_weight(p) for p in m_plays)
            avg_p = sum(m_plays) / len(m_plays) if m_plays else 0
            titles = [v.get("title", "")[:40] for v in m_videos[:5]]
            monthly_breakdown.append({
                "month": month,
                "count": len(m_videos),
                "play_weight_sum": round(total_pw, 1),
                "avg_plays": round(avg_p, 1),
                "sample_titles": titles,
            })

        report["monthly_breakdown"] = monthly_breakdown

        # 为 weighted_domains 补充 months_active
        if report.get("weighted_domains"):
            domain_months: dict[str, set[str]] = {}
            for batch_info in batch_domain_map:
                start_idx, end_idx = batch_info["video_indices"]
                batch_months: set[str] = set()
                for v in all_videos[start_idx:end_idx]:
                    ts = v.get("fav_time")
                    if ts:
                        try:
                            dt = datetime.fromtimestamp(int(ts), tz=timezone.utc)
                            batch_months.add(dt.strftime("%Y-%m"))
                        except (ValueError, OSError):
                            pass
                for domain in batch_info["domains"]:
                    domain_months.setdefault(domain, set()).update(batch_months)

            for wd in report["weighted_domains"]:
                wd["months_active"] = sorted(domain_months.get(wd["domain"], []))

    return report


def save_report(uid: str = None) -> Path:
    """运行分析并保存报告文件（JSON 格式）"""
    if not uid:
        uid = get_uid()

    log(f"\n  UID: {uid}")
    log(f"  模型: {llm.current_model_name()}")

    report = build_report(uid)
    report_path = BILI_FAV_HOME / f"analysis_report_{uid}.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    ds = report.get("data_scope", {})
    log(f"\n[完成] 报告已保存: {report_path}")
    log(f"       视频: {ds.get('videos', 0)} | "
        f"收藏夹: {ds.get('favorites', 0)} | "
        f"动态: {ds.get('dynamics', 0)}")
    if report.get("user_profile"):
        domains = report["user_profile"].get("domains", [])
        log(f"       兴趣领域: {'  '.join(domains)}")
    else:
        log(f"       兴趣画像: 不可用（Ollama 未运行）")

    ps = report.get("play_stats") or {}
    if ps:
        log(f"       播放量: 中位数{ps.get('median', '?')}  "
            f"最高{ps.get('max', '?')}")
    mb = report.get("monthly_breakdown") or []
    if mb:
        log(f"       月份跨度: {mb[0]['month']} ~ {mb[-1]['month']} ({len(mb)}个月)")

    return report_path


# ============================================================
#  文案生成
# ============================================================

DOMAIN_TAG_MAP = {
    "VOCALOID": ["VOCALOID/术力口爱好者", "初音ミク粉丝", "同人创作者", "MAD/AMV制作人"],
    "音乐": ["吉他爱好者", "指弹玩家", "乐队成员", "扒谱达人", "摇滚乐迷", "电子音乐爱好者", "国风音乐爱好者", "木吉他民谣党"],
    "游戏": ["独立游戏玩家", "游戏开发玩家", "Steam收藏家", "MC建筑师", "音游玩家", "原神旅行者", "CS2爱好者", "肉鸽玩家", "模拟经营控"],
    "开发": ["程序员", "后端开发", "前端开发", "全栈", "Linux党", "Docker玩家", "爬虫工程师", "AI训练师", "数据分析师"],
    "技术": ["程序员", "AI训练师", "数据分析师", "自动化脚本", "效率控"],
    "二次元": ["二次元爱好者", "番剧追更党", "漫画读者", "声优厨", "手办玩家"],
    "学习": ["学生党", "考研党", "语言学习者", "科普作者"],
    "电脑": ["数码发烧友", "DIY主机", "装机猿", "外设党", "机械键盘控"],
    "安全": ["网络安全爱好者", "逆向工程", "CTF选手", "渗透测试"],
    "网络": ["乐子人", "整活大师", "玩梗达人", "互联网嘴替"],
}


def _filter_tags(weighted_domains: list[dict]) -> str:
    """根据加权领域筛选相关标签子集，返回 prompt 中的标签列表文本"""
    full_tags = (
        "二次元爱好者、番剧追更党、漫画读者、声优厨、手办玩家、VOCALOID/术力口爱好者、初音ミク粉丝、"
        "吉他爱好者、指弹玩家、乐队成员、扒谱达人、摇滚乐迷、电子音乐爱好者、国风音乐爱好者、"
        "CS2爱好者、独立游戏玩家、游戏开发玩家、Steam收藏家、MC建筑师、音游玩家、原神旅行者、"
        "程序员、后端开发、前端开发、全栈、Linux党、Docker玩家、爬虫工程师、AI训练师、"
        "网络安全爱好者、逆向工程、CTF选手、"
        "乐子人、整活大师、玩梗达人、互联网嘴替、"
        "数码发烧友、DIY主机、装机猿、外设党、机械键盘控、"
        "学生党、考研党、猫奴、B站UP主、电影爱好者、美食爱好者"
    )
    if not weighted_domains:
        return full_tags

    relevant: set[str] = set()
    for wd in weighted_domains[:5]:
        domain = wd.get("domain", "")
        for key, tags in DOMAIN_TAG_MAP.items():
            if key in domain:
                relevant.update(tags)

    if not relevant:
        return full_tags
    return "、".join(sorted(relevant))


COPY_PROMPT = """你是一个B站用户成分分析专家。根据用户的收藏数据和兴趣画像，生成一份「成分分析」文案。

从以下标签池中选择匹配的标签（选择最具体的，不要超过5个，按匹配度从高到低排列）：

{tag_pool}

要求：
- labels：必须从上面标签池准确选取3-5个，一字不差不能自己编。如果一个都匹配不上则输出 ["?"]
- summary：一句话概括用户的视频分类领域（用顿号分隔）
- content（第二人称"你"，对用户说话，规则如下）：
  1. 开头一句话概括用户是什么类型的人（基于 labels 判断）
  2. 然后总结用户的兴趣方向和收藏偏好
  3. 不要列举任何具体视频标题或UP主
  4. 不要给建议，不要锐评吐槽
  5. 篇幅200-400字，简洁明了
- 【重要】全篇只能用陈述句，禁止反问句。
- 【重要】用户只是观众/收藏者，不是创作者也不是专家。绝对禁止："创作者"、"精通"、"无一不精"、"炉火纯青"、"造诣"、"高手"、"大师"、"深入研究"、"技术宅"、"技术大牛"、"大佬"。正确说法："你喜欢看XX"、"你关注XX"、"你的收藏显示你对XX感兴趣"
- B站成分分析风格，语言犀利直接带调侃，篇幅500-1000字，内容充实有细节

返回格式：
第一行：JSON（只放 labels 和 summary）
第二行：空行
第三行起：正文（纯文本，不要用 ``` 包裹，不要用 --- 分隔）"""


def generate_copy(uid: str = None, private: bool = False) -> dict | None:
    """读取报告，用 Ollama 生成文案"""
    if not uid:
        uid = get_uid()
    report_path = BILI_FAV_HOME / f"analysis_report_{uid}.json"
    if not report_path.exists():
        log("[错误] 报告文件不存在，请先运行分析")
        return None

    report = json.loads(report_path.read_text("utf-8"))

    # 私密模式：使用私密画像字段
    profile_key = "user_profile_private" if private else "user_profile"
    weighted_key = "weighted_domains_private" if private else "weighted_domains"
    copy_tag = "[私密]" if private else ""

    profile = report.get(profile_key) or report.get("user_profile")
    if not profile:
        log(f"[错误] 报告中无{copy_tag}用户兴趣画像")
        return None

    # 构建 prompt：只给画像摘要，不给具体视频（防止模型瞎编）
    summary = profile.get("summary", "")
    domains = "、".join(profile.get("domains", []))
    keywords = "、".join(profile.get("keywords", []))

    # 加入加权信息
    weighted = report.get(weighted_key) or report.get("weighted_domains") or []
    weighted_str = ""
    if weighted:
        weighted_str = "、".join(
            [f"{d['domain']}(评分{d['score']})" for d in weighted[:5]]
        )

    monthly = report.get("monthly_breakdown") or []
    monthly_str = ""
    if monthly:
        monthly_str = "、".join(
            [f"{m['month']}({m['count']}个)" for m in monthly]
        )

    play_stats = report.get("play_stats") or {}
    plays_info = ""
    if play_stats:
        plays_info = f"播放量统计：中位数{play_stats.get('median', '?')}，最高{play_stats.get('max', '?')}，最低{play_stats.get('min', '?')}"

    # 收藏夹分布
    fav_bd = report.get("favorite_breakdown") or []
    fav_info = ""
    if fav_bd:
        fav_info = "、".join(
            [f"{f['name']}({f['count']}个,均播放{f['avg_plays']:.0f})" for f in fav_bd[:5]]
        )

    # 动态标签池
    tag_pool = _filter_tags(weighted)
    prompt = COPY_PROMPT.format(tag_pool=tag_pool)

    user_text = (
        f"用户兴趣画像：{summary}\n\n"
        f"偏好领域：{domains}\n"
        f"关键词：{keywords}\n"
    )
    if weighted_str:
        user_text += f"加权兴趣评分：{weighted_str}\n"
    if monthly_str:
        user_text += f"收藏时间分布：{monthly_str}\n"
    if fav_info:
        user_text += f"收藏夹分布：{fav_info}\n"
    if plays_info:
        user_text += f"{plays_info}\n"
    user_text += "\n根据以上信息生成一份用户成分分析。"

    log("  正在生成文案...")
    try:
        for attempt in range(2):
            try:
                temp = 0.3 + attempt * 0.2
                text = llm.llm_chat([
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": user_text},
                ], temperature=temp)

                # 提取 JSON 部分（labels + summary）
                json_text = _extract_json(text)
                cleaned = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', json_text)
                result = json.JSONDecoder(strict=False).decode(cleaned)
                if not isinstance(result, dict):
                    raise ValueError(f"expected dict, got {type(result).__name__}")

                # 提取正文：JSON 之后的部分
                json_end = text.rfind('}')
                content = text[json_end+1:].strip()
                # 去掉可能的 content: 前缀
                content = re.sub(r'^content[：:\s]*', '', content)
                content = content.strip('"\' \n\r')
                result["content"] = content if content else ""

                if not result.get("content"):
                    raise ValueError("empty content")

                # 清理多余分隔符
                content = re.sub(r'^[-—=]{3,}\s*', '', content).strip()
                # 后处理：替换违禁词
                c = result["content"]
                c = c.replace("创作者", "爱好者")
                c = c.replace("精通", "喜欢")
                c = c.replace("无一不精", "涉猎很广")
                c = c.replace("炉火纯青", "很有热情")
                c = c.replace("技术大牛", "爱好者")
                c = c.replace("高手", "爱好者")
                c = c.replace("大师", "爱好者")
                c = c.replace("大佬", "爱好者")
                c = c.replace("彰显了你的", "说明你")
                # 清除具体书名号引用（视频标题）
                c = re.sub(r'《[^》]+》', '相关内容', c)
                # 清除建议句式
                c = c.replace('别忘了', '不过')
                c = c.replace('记得', '')
                # 反问句转陈述句
                c = c.replace('？', '。')
                # 清除 markdown 代码块残留
                c = re.sub(r'^```\w*\n?', '', c)
                c = re.sub(r'\n?```$', '', c)
                # 清除分隔符残留
                c = re.sub(r'^[-—=]{3,}\s*', '', c)
                c = re.sub(r'\n[-—=]{3,}\s*', '\n', c)
                c = c.strip()
                result["content"] = c
                break
            except Exception as e:
                if attempt == 0:
                    log(f"  重试...")
                    continue
                raise

        copy_name = f"copy_{uid}_private.json" if private else f"copy_{uid}.json"
        copy_path = BILI_FAV_HOME / copy_name
        copy_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf-8")
        log(f"[完成] {copy_tag}文案已生成: {copy_path}")
        return result
    except Exception as e:
        log(f"[错误] {copy_tag}文案生成失败: {e}")
        return None


# ============================================================
#  导出报告（人类可读格式）
# ============================================================


def _fmt_num(n: float) -> str:
    """格式化大数字：1234567 → 1,234,567"""
    if n >= 100000000:
        return f"{n/100000000:.2f}亿"
    if n >= 10000:
        return f"{n/10000:.1f}万"
    return f"{n:.0f}"


def export_report(uid: str = None, output_path: str = None) -> Path | None:
    """导出人类可读的文本报告。

    Args:
        uid: 用户UID
        output_path: 保存路径。若为 None 则默认 analysis_report_{uid}.txt
    """
    if not uid:
        uid = get_uid()
    report_path = BILI_FAV_HOME / f"analysis_report_{uid}.json"
    if not report_path.exists():
        log("[错误] 报告文件不存在，请先运行分析 (python analyze.py)")
        return None

    report = json.loads(report_path.read_text("utf-8"))

    # 解析输出路径
    if not output_path:
        output_path = str(BILI_FAV_HOME / f"analysis_report_{uid}.txt")
        log(f"  保存到: {output_path}")
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []

    def add(s: str = ""):
        lines.append(s)

    def sep():
        add("─" * 56)

    # ── 标题 ──
    add("╔" + "═" * 54 + "╗")
    add("║" + "  B站收藏数据兴趣分析报告".center(50) + "║")
    add("╚" + "═" * 54 + "╝")
    add(f"  用户ID: {uid}")
    add(f"  生成时间: {report.get('generated_at', '?')[:19]}")
    add(f"  模型: {report.get('model', '?')}")

    # ── 数据概览 ──
    ds = report.get("data_scope", {})
    add()
    sep()
    add("  📊 数据概览")
    sep()
    add(f"  视频数: {ds.get('videos', 0)}")
    add(f"  收藏夹: {ds.get('favorites', 0)} 个")
    if ds.get("favorites_private"):
        add(f"  私密收藏夹: {ds['favorites_private']} 个（已跳过）")
    mb = report.get("monthly_breakdown") or []
    if mb:
        add(f"  月份跨度: {mb[0]['month']} ~ {mb[-1]['month']} ({len(mb)}个月)")

    # ── 兴趣画像 ──
    profile = report.get("user_profile")
    if profile:
        add()
        sep()
        add("  🎯 兴趣画像")
        sep()
        domains = profile.get("domains", [])
        if domains:
            add(f"  领域: {'  '.join(domains)}")
        style = profile.get("style_tendency", "")
        if style:
            add(f"  风格: {style}")
        keywords = profile.get("keywords", [])
        if keywords:
            add(f"  关键词: {', '.join(keywords[:8])}")
        summary = profile.get("summary", "")
        if summary:
            add()
            for para in summary.split("\n"):
                if para.strip():
                    add(f"  {para.strip()}")

    # ── 播放量统计 ──
    ps = report.get("play_stats") or {}
    if ps:
        add()
        sep()
        add("  📈 播放量统计")
        sep()
        add(f"  总计: {_fmt_num(ps.get('total', 0))}")
        add(f"  平均: {_fmt_num(ps.get('mean', 0))}")
        add(f"  中位数: {_fmt_num(ps.get('median', 0))}")
        add(f"  最高: {_fmt_num(ps.get('max', 0))}")
        add(f"  最低: {_fmt_num(ps.get('min', 0))}")
        buckets = ps.get("buckets", [])
        if buckets:
            add()
            add(f"  ── 播放量分布 ──")
            for b in buckets:
                add(f"    {b['label']}: {b['count']} 个 ({b['pct']}%)")

    # ── 收藏夹分解 ──
    fav_bd = report.get("favorite_breakdown") or []
    if fav_bd:
        add()
        sep()
        add("  📁 收藏夹分解")
        sep()
        for f in fav_bd:
            add(f"  {f['name']}")
            add(f"    视频: {f['count']} 个 | 总播放: {_fmt_num(f['total_plays'])} | 均播放: {_fmt_num(f['avg_plays'])}")

    # ── 月度分解 ──
    if mb:
        add()
        sep()
        add("  📅 月度收藏趋势")
        sep()
        for m in mb:
            add(f"  {m['month']}")
            add(f"    视频数: {m['count']} | 权重和: {m['play_weight_sum']} | 均播放: {_fmt_num(m.get('avg_plays', 0))}")
            samples = m.get("sample_titles", [])
            if samples:
                for t in samples[:3]:
                    add(f"    · {t}")

    # ── 加权领域 ──
    weighted = report.get("weighted_domains") or []
    if weighted:
        add()
        sep()
        add("  🏷️  兴趣领域权重")
        sep()
        for wd in weighted:
            months = wd.get("months_active", [])
            months_str = f" [{', '.join(months)}]" if months else ""
            add(f"  {wd['domain']}: 评分 {wd.get('score', '?')}%{months_str}")

    # ── 视频原始列表 ──
    videos = report.get("videos", [])
    if videos:
        add()
        sep()
        add(f"  📋 视频列表（共 {len(videos)} 个）")
        sep()
        for i, v in enumerate(videos, 1):
            title = v.get("title", "?")
            author = v.get("author", "?")
            plays = v.get("plays", "")
            fav = v.get("favorite", "")
            add(f"  {i:3d}. {title[:48]}")
            add(f"       {author}  |  {plays}  |  [{fav}]")

    # 保存
    out.write_text("\n".join(lines), encoding="utf-8")
    log(f"\n[完成] 报告已导出: {out.resolve()}")
    log(f"       共 {len(lines)} 行，{out.stat().st_size} 字节")
    return out


# ============================================================
#  导出 HTML 报告
# ============================================================


def export_html(uid: str = None, output_path: str = None) -> Path | None:
    """导出为可交互的 HTML 报告（含可点击的视频链接）"""
    if not uid:
        uid = get_uid()
    report_path = BILI_FAV_HOME / f"analysis_report_{uid}.json"
    if not report_path.exists():
        log("[错误] 报告文件不存在")
        return None

    report = json.loads(report_path.read_text("utf-8"))
    if not output_path:
        output_path = str(BILI_FAV_HOME / f"analysis_report_{uid}.html")
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    ds = report.get("data_scope", {})
    profile = report.get("user_profile") or {}
    ps = report.get("play_stats") or {}
    mb = report.get("monthly_breakdown") or []
    fav_bd = report.get("favorite_breakdown") or []
    weighted = report.get("weighted_domains") or []
    videos = report.get("videos", [])

    def h(s):
        """HTML 转义"""
        return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

    months_html = ""
    groups: dict[str, list] = {}
    for v in videos:
        ts = v.get("fav_time")
        if ts:
            from datetime import datetime, timezone
            try:
                m = datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m")
            except Exception:
                m = "???"
        else:
            m = "???"
        groups.setdefault(m, []).append(v)
    for month in sorted(groups.keys(), reverse=True):
        vs = groups[month]
        items = ""
        for v in vs:
            link = v.get("link", "") or f"https://www.bilibili.com/video/{v.get('bvid', '')}"
            plays = h(v.get("plays", ""))
            author = h(v.get("author", ""))
            fav = h(v.get("favorite", ""))
            title = h(v.get("title", "?"))
            items += f"""<a href="{link}" target="_blank" class="vi">
  <span class="vi-t">{title}</span>
  <span class="vi-m">{author}  |  {plays}  |  [{fav}]</span>
</a>"""
        months_html += f"""<div class="mg">
  <div class="mh">{month} <span class="mc">{len(vs)} 个</span></div>
  {items}
</div>"""

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><title>B站收藏分析报告 - {uid}</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif; background:#0f0f1a; color:rgba(255,255,255,0.8); display:flex; min-height:100vh; }}
.sb {{ width:400px; min-width:400px; height:100vh; overflow-y:auto; border-right:1px solid rgba(255,255,255,0.06); background:rgba(255,255,255,0.02); }}
.sb-h {{ padding:20px 20px 12px; font-size:13px; font-weight:600; color:rgba(255,255,255,0.4); border-bottom:1px solid rgba(255,255,255,0.04); }}
.sb-l {{ padding:8px 0; }}
.sb::-webkit-scrollbar {{ width:4px; }}
.sb::-webkit-scrollbar-thumb {{ background:rgba(255,255,255,0.08); border-radius:2px; }}
.mg {{ margin-bottom:4px; }}
.mh {{ padding:10px 20px 6px; font-size:11px; font-weight:600; color:rgba(255,255,255,0.25); }}
.mc {{ color:rgba(255,255,255,0.15); font-weight:400; }}
.vi {{ display:block; padding:8px 20px; text-decoration:none; color:inherit; transition:background 0.15s; cursor:pointer; }}
.vi:hover {{ background:rgba(255,255,255,0.04); }}
.vi-t {{ display:block; font-size:12.5px; line-height:1.4; color:rgba(255,255,255,0.75); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
.vi-m {{ font-size:11px; color:rgba(255,255,255,0.25); }}
.main {{ flex:1; padding:32px 40px; max-width:800px; overflow-y:auto; }}
.main::-webkit-scrollbar {{ width:4px; }}
.main::-webkit-scrollbar-thumb {{ background:rgba(255,255,255,0.08); border-radius:2px; }}
h1 {{ font-size:22px; font-weight:600; color:#fff; margin-bottom:4px; }}
.sub {{ color:rgba(255,255,255,0.35); font-size:13px; margin-bottom:32px; }}
.card {{ background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.06); border-radius:16px; padding:20px 24px; margin-bottom:16px; }}
.card h2 {{ font-size:14px; font-weight:600; color:rgba(255,255,255,0.6); margin-bottom:12px; display:flex; align-items:center; gap:8px; }}
.stat-row {{ display:flex; gap:16px; flex-wrap:wrap; }}
.stat-item {{ background:rgba(255,255,255,0.03); border-radius:10px; padding:12px 16px; min-width:100px; }}
.stat-item .num {{ font-size:18px; font-weight:600; color:#00a1d6; }}
.stat-item .label {{ font-size:11px; color:rgba(255,255,255,0.35); margin-top:2px; }}
.bucket {{ display:inline-block; padding:3px 10px; border-radius:6px; font-size:11px; margin:2px; background:rgba(255,255,255,0.04); color:rgba(255,255,255,0.6); }}
.tag {{ display:inline-block; padding:4px 12px; border-radius:20px; font-size:12px; margin:3px; background:rgba(0,161,214,0.1); border:1px solid rgba(0,161,214,0.15); color:#00a1d6; }}
.summary {{ font-size:13px; line-height:1.7; color:rgba(255,255,255,0.65); padding:12px; background:rgba(0,0,0,0.15); border-radius:10px; }}
.fb {{ display:flex; gap:12px; flex-wrap:wrap; }}
.fb-item {{ background:rgba(255,255,255,0.03); border-radius:10px; padding:12px 16px; flex:1; min-width:140px; }}
.fb-item .fn {{ font-size:12px; color:rgba(255,255,255,0.5); margin-bottom:4px; }}
.fb-item .fv {{ font-size:14px; color:#fff; }}
.wd {{ display:flex; gap:8px; flex-wrap:wrap; }}
.wd-item {{ background:rgba(118,75,162,0.1); border:1px solid rgba(118,75,162,0.2); border-radius:20px; padding:4px 14px; font-size:12px; color:#a78bfa; }}
.copy-text {{ font-size:13px; line-height:1.8; white-space:pre-wrap; color:rgba(255,255,255,0.65); padding:12px; background:rgba(0,0,0,0.15); border-radius:10px; }}
</style>
</head>
<body>
<div class="sb">
  <div class="sb-h">收藏视频 &middot; {len(videos)} 个</div>
  <div class="sb-l">{months_html}</div>
</div>
<div class="main">
  <h1>B站收藏兴趣分析报告</h1>
  <div class="sub">UID: {h(uid)} &middot; {h(report.get("generated_at","")[:10])} &middot; 模型: {h(report.get("model","?"))}</div>

  <div class="card">
    <h2>&#x1F4CA; 数据概览</h2>
    <div class="stat-row">
      <div class="stat-item"><div class="num">{ds.get("videos",0)}</div><div class="label">视频</div></div>
      <div class="stat-item"><div class="num">{ds.get("favorites",0)}</div><div class="label">收藏夹</div></div>
      <div class="stat-item"><div class="num">{len(mb)}</div><div class="label">月份</div></div>
      <div class="stat-item"><div class="num">{h(_fmt_num(ps.get("total",0)))}</div><div class="label">总播放</div></div>
    </div>
  </div>"""

    if profile:
        domains = profile.get("domains", [])
        keywords = profile.get("keywords", [])
        summary = profile.get("summary", "")
        html += f"""<div class="card">
  <h2>&#x1F3AF; 兴趣画像</h2>
  <div style="margin-bottom:10px;">{" ".join(f'<span class="tag">{h(d)}</span>' for d in domains)}</div>"""
        if keywords:
            html += f"""<div style="margin-bottom:10px;"><span style="font-size:11px;color:rgba(255,255,255,0.3);">关键词: </span>{" ".join(f'<span class="tag" style="background:rgba(255,255,255,0.03);border-color:rgba(255,255,255,0.08);color:rgba(255,255,255,0.5);font-size:11px;">{h(k)}</span>' for k in keywords[:10])}</div>"""
        if summary:
            html += f"""<div class="summary">{h(summary)}</div>"""
        html += "</div>"

    if ps:
        buckets = ps.get("buckets", [])
        html += f"""<div class="card">
  <h2>&#x1F4C8; 播放量统计</h2>
  <div class="stat-row" style="margin-bottom:12px;">
    <div class="stat-item"><div class="num">{h(_fmt_num(ps.get("mean",0)))}</div><div class="label">平均</div></div>
    <div class="stat-item"><div class="num">{h(_fmt_num(ps.get("median",0)))}</div><div class="label">中位数</div></div>
    <div class="stat-item"><div class="num">{h(_fmt_num(ps.get("max",0)))}</div><div class="label">最高</div></div>
    <div class="stat-item"><div class="num">{h(_fmt_num(ps.get("min",0)))}</div><div class="label">最低</div></div>
  </div>
  <div>{" ".join(f'<span class="bucket">{h(b["label"])}: {b["count"]} ({b["pct"]}%)</span>' for b in buckets)}</div>
</div>"""

    if fav_bd:
        items = "".join(f'<div class="fb-item"><div class="fn">{h(f["name"])}</div><div class="fv">{f["count"]} 个 &middot; {_fmt_num(f["total_plays"])}</div></div>' for f in fav_bd)
        html += f"""<div class="card">
  <h2>&#x1F4C1; 收藏夹分解</h2>
  <div class="fb">{items}</div>
</div>"""

    if weighted:
        items = "".join(f'<span class="wd-item">{h(w["domain"])} {w.get("score","?")}%</span>' for w in weighted)
        html += f"""<div class="card">
  <h2>&#x1F3F7;&#xFE0F; 兴趣领域权重</h2>
  <div class="wd">{items}</div>
</div>"""

    # 文案结果
    copy_path = BILI_FAV_HOME / f"copy_{uid}.json"
    if copy_path.exists():
        try:
            cdata = json.loads(copy_path.read_text("utf-8"))
            ccontent = cdata.get("content", "")
            if ccontent:
                html += f"""<div class="card">
  <h2>&#x1F4DD; 成分分析文案</h2>
  <div class="copy-text">{h(ccontent)}</div>
</div>"""
        except Exception:
            pass

    html += "</div></body></html>"

    out.write_text(html, encoding="utf-8")
    log(f"\n[完成] HTML 报告已导出: {out.resolve()}")
    log(f"       大小: {out.stat().st_size / 1024:.0f} KB")
    return out


# ============================================================
# CLI 入口
# ============================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="B站数据分析 (Ollama)")
    parser.add_argument("--uid", type=str, help="用户UID")
    parser.add_argument("--copy", action="store_true", help="生成文案（基于已有报告）")
    parser.add_argument("--private", action="store_true", help="配合 --copy 使用，分析私密内容")
    parser.add_argument("--export", action="store_true", help="导出人类可读的报告文本")
    parser.add_argument("--export-html", action="store_true", help="导出 HTML 报告（含视频链接）")
    parser.add_argument("--output", type=str, help="导出路径（配合 --export/--export-html 使用）")
    args = parser.parse_args()

    uid = args.uid or get_uid()
    if not uid:
        print("[错误] 未指定 UID，且 bili_uid.txt 不存在")
        sys.exit(1)

    if args.copy:
        result = generate_copy(uid, private=args.private)
        if result:
            print(f"\n标题: {result.get('title')}")
            print(f"风格: {result.get('style')}")
            print(f"\n{result.get('content', '')[:200]}...")
    elif args.export_html:
        export_html(uid, args.output)
    elif args.export:
        if not args.output:
            default_path = str(BILI_FAV_HOME / f"analysis_report_{uid}.txt")
            user_path = input(f"  保存路径（Enter 使用默认） [{default_path}]: ").strip()
            args.output = user_path or default_path
        export_report(uid, args.output)
    else:
        save_report(uid)
