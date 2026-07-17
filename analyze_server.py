#!/usr/bin/env python3
"""
B站数据分析服务器

接收爬虫提交的采集数据，保存到本地目录后调用 Ollama 分析引擎，
返回分析报告文本及文件路径。

启动：
  python analyze_server.py                    # 默认端口 18235
  python analyze_server.py --port 8080         # 指定端口
  python analyze_server.py --host 0.0.0.0      # 监听所有网卡

环境变量：
  OLLAMA_HOST  默认 http://localhost:11434
  OLLAMA_MODEL 默认 qwen2.5:7b
"""

import json
import os
import re
import sys
from pathlib import Path

# 必须在 FastAPI import 之前设置路径
sys.path.insert(0, str(Path(__file__).parent.resolve()))

# ============================================================
# 路径与 analyze.py 保持一致
# ============================================================

_base_dir = Path(__file__).parent.resolve()
if os.environ.get("BILI_PORTABLE", "1") == "0":
    _base_dir = Path.home() / ".bilibili_fav"

BILI_FAV_HOME = _base_dir


def safe_filename(name: str) -> str:
    """将字符串转为安全文件名"""
    return re.sub(r'[\\/:*?"<>|]', "_", name).strip() or "unnamed"


# ============================================================
# FastAPI 应用
# ============================================================

from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel

app = FastAPI(
    title="BiliAnalyzer",
    description="B站数据采集分析服务器 — 接收爬虫数据，使用本地 Ollama 模型分析",
    version="1.0.0",
)


# ---------- 请求/响应模型 ----------

class FavoriteItem(BaseModel):
    title: str = ""
    author: str = ""
    plays: str = ""
    danmaku: str = ""
    duration: str = ""
    link: str = ""
    _favorite: str = ""


class DynamicItem(BaseModel):
    id: str = ""
    type: str = ""
    time: str = ""
    author: str = ""
    content: str | None = None
    video_bvid: str | None = None
    video_title: str | None = None
    likes: int = 0
    comments: int = 0
    reposts: int = 0
    is_forward: bool = True
    forward_content: str | None = None
    original_author: str | None = None


class AnalyzeRequest(BaseModel):
    uid: str
    favorites: dict[str, list[FavoriteItem]] = {}
    dynamics: list[DynamicItem] = []


class AnalyzeResponse(BaseModel):
    status: str  # "success" | "error"
    report_path: str = ""
    report: str = ""
    message: str = ""


# ---------- API ----------


@app.get("/api/health")
async def health():
    """健康检查 + Ollama 状态"""
    ollama_ok = False
    ollama_models = []

    try:
        import urllib.request
        base = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        with urllib.request.urlopen(f"{base}/api/tags", timeout=5) as resp:
            data = json.loads(resp.read())
        ollama_models = [m["name"] for m in data.get("models", [])]
        ollama_ok = True
    except Exception:
        pass

    return {
        "status": "ok",
        "ollama": ollama_ok,
        "models": ollama_models,
        "bili_fav_home": str(BILI_FAV_HOME),
    }


def _save_and_analyze(req: AnalyzeRequest) -> str:
    """保存数据、运行分析、返回报告文本（同步，在后台线程中执行）"""
    # 1. 保存收藏夹数据
    data_dir = BILI_FAV_HOME / f"data_{req.uid}"
    data_dir.mkdir(parents=True, exist_ok=True)

    for fav_name, videos in req.favorites.items():
        safe_name = safe_filename(fav_name)
        path = data_dir / f"{safe_name}.json"
        # 转 dict 并注入 _favorite 字段
        items = []
        for v in videos:
            d = v.model_dump()
            d["_favorite"] = fav_name
            items.append(d)
        path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")

    # 2. 保存动态数据
    if req.dynamics:
        dynamics_dir = BILI_FAV_HOME / f"dynamics_{req.uid}"
        dynamics_dir.mkdir(parents=True, exist_ok=True)
        path = dynamics_dir / f"uid_{req.uid}_simple.json"
        path.write_text(
            json.dumps([d.model_dump() for d in req.dynamics], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # 3. 运行分析
    from analyze import run_analysis

    report = run_analysis(req.uid)

    # 4. 保存报告
    report_path = BILI_FAV_HOME / f"analysis_report_{req.uid}.txt"
    report_path.write_text(report, encoding="utf-8")

    return report


@app.post("/api/analyze", response_model=AnalyzeResponse)
async def analyze(req: AnalyzeRequest, background_tasks: BackgroundTasks):
    """接收采集数据，保存后分析，返回报告"""
    if not req.uid:
        raise HTTPException(status_code=400, detail="uid 不能为空")
    if not req.favorites and not req.dynamics:
        raise HTTPException(status_code=400, detail="至少需要 favorites 或 dynamics 数据")

    try:
        report = _save_and_analyze(req)
        report_filename = f"analysis_report_{req.uid}.txt"
        report_path = str(BILI_FAV_HOME / report_filename)

        return AnalyzeResponse(
            status="success",
            report_path=report_path,
            report=report,
            message="分析完成",
        )
    except Exception as e:
        import traceback
        return AnalyzeResponse(
            status="error",
            message=f"分析失败: {e}\n{traceback.format_exc()}",
        )


@app.get("/api/report/{uid}")
async def get_report(uid: str):
    """获取已有分析报告"""
    report_path = BILI_FAV_HOME / f"analysis_report_{uid}.txt"
    if not report_path.exists():
        raise HTTPException(status_code=404, detail="报告不存在，请先调用 POST /api/analyze")
    return {
        "status": "success",
        "report_path": str(report_path),
        "report": report_path.read_text(encoding="utf-8"),
    }


# ============================================================
# 启动入口
# ============================================================

def main():
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser(description="B站数据分析服务器")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址")
    parser.add_argument("--port", type=int, default=18235, help="监听端口")
    parser.add_argument("--reload", action="store_true", help="开发模式自动重载")
    args = parser.parse_args()

    print(f"  BiliAnalyzer 分析服务器启动")
    print(f"   监听: http://{args.host}:{args.port}")
    print(f"   数据目录: {BILI_FAV_HOME}")
    print(f"   Ollama: {os.environ.get('OLLAMA_HOST', 'http://localhost:11434')}")
    print(f"   模型: {os.environ.get('OLLAMA_MODEL', 'qwen2.5:7b')}")
    print(f"   API 文档: http://{args.host}:{args.port}/docs")
    print()

    uvicorn.run(app, host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    import argparse
    main()
