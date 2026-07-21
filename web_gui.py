#!/usr/bin/env python3
"""
B站数据采集 — Web 界面版

全本地流程：登录 -> 采集 -> 分析(Ollama) -> 生成文案(Ollama) -> 显示
"""

import json
import threading
import webbrowser
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
import sys
import os

sys.path.insert(0, str(Path(__file__).parent))

_base_dir = Path(__file__).parent.resolve()
if os.environ.get("BILI_PORTABLE", "1") == "0":
    _base_dir = Path.home() / ".bilibili_fav"

BILI_FAV_HOME = _base_dir
UID_FILE = BILI_FAV_HOME / "bili_uid.txt"

app_state = {
    "uid": None,
    "status": "checking",
    "message": "",
    "total_videos": 0,
    "dest_url": "",
    "copy_result": None,
    "copy_title": "",
    "collect_progress": "",
}


def _load_private_folders(uid: str) -> set[str]:
    """读取 folders.json，返回私密收藏夹名称集合"""
    try:
        p = BILI_FAV_HOME / f"data_{uid}" / "folders.json"
        if not p.exists():
            return set()
        data = json.loads(p.read_text("utf-8"))
        return {f["name"] for f in data if f.get("private")}
    except Exception:
        return set()


def load_videos_grouped(uid: str) -> dict[str, list]:
    """从 JSON 文件读取视频，按 fav_time 的月份分组（新→旧），标记私密视频"""
    try:
        from datetime import datetime, timezone

        private_folders = _load_private_folders(uid)
        data_dir = _base_dir / f"data_{uid}"
        months: dict[str, list] = {}
        if not data_dir.exists():
            return {}

        for fp in sorted(data_dir.glob("*.json")):
            if fp.stem.startswith(".") or fp.stem in ("folders", "liked_videos"):
                continue
            fav_name = fp.stem
            videos = json.loads(fp.read_text("utf-8"))
            for v in videos:
                v["is_private"] = fav_name in private_folders
                v["favorite"] = fav_name
                ts = v.get("fav_time")
                if ts:
                    month = datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m")
                else:
                    month = "???"
                months.setdefault(month, []).append(v)
        return dict(sorted(months.items(), reverse=True))
    except Exception:
        return {}


def check_login() -> str | None:
    if not UID_FILE.exists():
        return None
    uid = UID_FILE.read_text().strip()
    if not uid:
        return None
    user_dir = BILI_FAV_HOME / f"user_data_{uid}"
    if not user_dir.exists():
        return None
    return uid


def do_login():
    try:
        from bili_common import find_local_browser, do_login as _do_login
        from playwright.sync_api import sync_playwright

        local_browser = find_local_browser()
        if not local_browser:
            from bili_common import check_chromium, install_chromium
            if not check_chromium():
                app_state["message"] = "Downloading Chromium, please wait..."
                try:
                    install_chromium()
                except Exception as e:
                    app_state["status"] = "error"
                    app_state["message"] = f"Download failed: {e}"
                    return

        with sync_playwright() as p:
            uid = _do_login(p)
        app_state["uid"] = uid
        app_state["status"] = "logged_in"
        app_state["message"] = "Login OK"
    except Exception as e:
        app_state["status"] = "error"
        app_state["message"] = str(e)


def do_collect():
    """通过子进程运行采集（写日志文件避免管道死锁）"""
    import subprocess, sys, time, tempfile
    try:
        venv_python = sys.executable
        bilbil = _base_dir / "bilbil.py"
        uid = app_state.get("uid", "")
        log_file = _base_dir / "data" / f"collect_{uid}.log" if uid else _base_dir / "data" / "collect.log"
        log_file.parent.mkdir(parents=True, exist_ok=True)

        app_state["message"] = "正在打开浏览器采集数据..."
        app_state["collect_progress"] = "启动浏览器..."

        with open(log_file, "w", encoding="utf-8") as fp:
            cmd = [venv_python, "-u", str(bilbil), "--uid", uid, "--incremental"]
            if sys.platform == "win32":
                cmd.append("--visible")
            proc = subprocess.Popen(
                cmd,
                stdout=fp, stderr=subprocess.STDOUT,
                text=True,
            )

            # 轮询进程 + 读出最后一行到 collect_progress
            t0 = time.time()
            timeout = 600  # 10分钟超时
            while proc.poll() is None:
                time.sleep(1)
                # 读最后一行日志
                try:
                    with open(log_file, "r", encoding="utf-8") as lf:
                        last = list(lf)[-1:]
                        if last:
                            app_state["collect_progress"] = last[-1].strip()
                except Exception:
                    pass
                if time.time() - t0 > timeout:
                    proc.kill()
                    raise TimeoutError(f"采集超时（{timeout}s）")

            rc = proc.wait()

        # 读取完整日志
        lines = log_file.read_text(encoding="utf-8").strip().split("\n")
        if rc == 0:
            app_state["status"] = "done"
            app_state["message"] = "采集完成！"
            app_state["collect_progress"] = lines[-1] if lines else ""
            # 从日志解析视频数（"全部完成！共 88 个视频"）
            import re
            for line in lines:
                m = re.search(r"全部完成！共 (\d+) 个视频", line)
                if m:
                    app_state["total_videos"] = int(m.group(1))
                    break
        else:
            raise RuntimeError("\n".join(lines[-5:]))

    except Exception as e:
        app_state["status"] = "error"
        app_state["message"] = f"采集失败: {e}"
        import traceback
        app_state["collect_progress"] = traceback.format_exc()


def do_analyze():
    try:
        from analyze import save_report
        report_path = save_report(app_state["uid"])

        # 可选：发送原始报告到机 C
        url = app_state.get("dest_url", "").strip()
        if url:
            from submit_client import http_send_report
            http_send_report(str(report_path), url)

        app_state["status"] = "analyzed"
        app_state["message"] = "分析完成，可生成文案"
    except Exception as e:
        app_state["status"] = "error"
        app_state["message"] = f"Analysis failed: {e}"


def do_generate_copy():
    """本地 Ollama 生成文案"""
    try:
        from analyze import generate_copy
        result = generate_copy(app_state["uid"])
        if result:
            app_state["copy_result"] = result
            app_state["copy_title"] = result.get("title", "文案结果")
            app_state["status"] = "copy_done"
            app_state["message"] = "文案已生成"
        else:
            app_state["status"] = "error"
            app_state["message"] = "文案生成失败（检查 LLM 配置：右上角模型选择器是否已切换到 DeepSeek 并填入 API Key）"
    except Exception as e:
        app_state["status"] = "error"
        app_state["message"] = f"Copy generation failed: {e}"


def do_switch_account():
    """清除所有用户数据，回到登录页"""
    import shutil
    uid = app_state.get("uid", "")
    # 清除当前用户的数据目录
    for d in [f"user_data_{uid}", f"data_{uid}", f"dynamics_{uid}",
              f"user_data", f"data", f"dynamics"]:
        p = Path(d)
        if p.exists():
            shutil.rmtree(str(p))
    # 清除文件
    for f in ["bili_uid.txt", f"analysis_report_{uid}.json", f"copy_{uid}.json"]:
        p = Path(f)
        if p.exists():
            p.unlink()
    # 重置状态
    app_state["uid"] = None
    app_state["status"] = "need_login"
    app_state["message"] = "已切换账号，请重新登录"
    app_state["total_videos"] = 0
    app_state["copy_result"] = None
    app_state["copy_title"] = ""


HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>BiliCollector</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
            background: #0f0f1a;
            height: 100vh; overflow: hidden;
            display: flex;
            color: rgba(255,255,255,0.8);
        }
        /* 近期动向 */
        .liked-section { border-bottom: 1px solid rgba(255,255,255,0.04); }
        .liked-header {
            padding: 10px 20px; cursor: pointer;
            display: flex; align-items: center; gap: 6px;
            font-size: 11px; font-weight: 600;
            color: rgba(255,255,255,0.3);
            letter-spacing: 0.3px;
            user-select: none; transition: color 0.15s;
        }
        .liked-header:hover { color: rgba(255,255,255,0.5); }
        .liked-header .arrow { transition: transform 0.2s; font-size: 10px; }
        .liked-header .arrow.open { transform: rotate(90deg); }
        .liked-body { overflow: hidden; max-height: 0; transition: max-height 0.25s ease; }
        .liked-body.open { max-height: 600px; }
        .liked-item {
            padding: 8px 20px;
            border-bottom: 1px solid rgba(255,255,255,0.02);
        }
        .liked-item:last-child { border-bottom: none; }
        .liked-item .li-title {
            font-size: 12px; color: rgba(255,255,255,0.7);
            margin-bottom: 4px;
            overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
        }
        .liked-item .li-tags { display: flex; flex-wrap: wrap; gap: 4px; }
        .liked-item .li-tag {
            font-size: 10px; padding: 2px 6px;
            background: rgba(0,161,214,0.12);
            color: rgba(0,161,214,0.7);
            border-radius: 3px;
        }
        .liked-empty { padding: 16px 20px; font-size: 11px; color: rgba(255,255,255,0.15); }
        .sidebar {
            width: 380px; min-width: 380px;
            height: 100vh;
            border-right: 1px solid rgba(255,255,255,0.06);
            display: flex; flex-direction: column;
            background: rgba(255,255,255,0.02);
        }
        .sidebar-header {
            padding: 20px 20px 12px;
            font-size: 13px; font-weight: 600;
            color: rgba(255,255,255,0.4);
            letter-spacing: 0.5px;
            border-bottom: 1px solid rgba(255,255,255,0.04);
            display: flex; align-items: center; justify-content: space-between;
        }
        .sidebar-toggle { display: flex; align-items: center; gap: 5px; cursor: pointer; font-size: 10px; font-weight: 400; color: rgba(255,255,255,0.2); user-select: none; }
        .sidebar-toggle:hover { color: rgba(255,255,255,0.4); }
        .sidebar-toggle input { accent-color: #00a1d6; }
        .sidebar-list {
            flex: 1; overflow-y: auto; padding: 8px 0;
        }
        .sidebar-list::-webkit-scrollbar { width: 4px; }
        .sidebar-list::-webkit-scrollbar-track { background: transparent; }
        .sidebar-list::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.08); border-radius: 2px; }

        .month-group { margin-bottom: 4px; }
        .month-header {
            padding: 10px 20px 6px;
            font-size: 11px; font-weight: 600;
            color: rgba(255,255,255,0.25);
            letter-spacing: 0.3px;
        }
        .video-item {
            display: flex; align-items: center; gap: 10px;
            padding: 8px 20px; cursor: pointer;
            transition: background 0.15s;
            text-decoration: none; color: inherit;
        }
        .video-item:hover { background: rgba(255,255,255,0.04); }
        .video-item .v-title {
            flex: 1; font-size: 12.5px; line-height: 1.4;
            color: rgba(255,255,255,0.75);
            overflow: hidden; text-overflow: ellipsis;
            display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
        }
        .video-item .v-meta {
            font-size: 11px; color: rgba(255,255,255,0.25);
            white-space: nowrap; flex-shrink: 0;
        }
        .video-item .v-plays { font-size: 11px; color: rgba(255,255,255,0.2); white-space: nowrap; flex-shrink: 0; }
        .video-item .v-link-icon {
            flex-shrink: 0; width: 16px; height: 16px;
            opacity: 0.3; transition: opacity 0.15s;
            display: flex; align-items: center; justify-content: center;
        }
        .video-item:hover .v-link-icon { opacity: 0.7; }
        .sidebar-empty {
            padding: 40px 20px; text-align: center;
            font-size: 13px; color: rgba(255,255,255,0.2);
        }

        .main {
            flex: 1; display: flex; align-items: center; justify-content: center;
            min-width: 0; padding: 20px;
        }
        .main::before {
            content: '';
            position: fixed;
            top: -50%; left: -50%;
            width: 200%; height: 200%;
            background: radial-gradient(circle at 30% 40%, rgba(0,161,214,0.06) 0%, transparent 50%),
                        radial-gradient(circle at 70% 60%, rgba(118,75,162,0.06) 0%, transparent 50%);
            animation: bgFloat 20s ease-in-out infinite;
            pointer-events: none;
        }
        @keyframes bgFloat { 0%,100%{transform:translate(0,0)} 50%{transform:translate(-2%,-2%)} }
        .card {
            position: relative; z-index: 1; width: 480px; max-width: 100%;
            background: rgba(255,255,255,0.03);
            backdrop-filter: blur(20px);
            border: 1px solid rgba(255,255,255,0.06);
            border-radius: 24px;
            padding: 40px 36px;
            text-align: center;
            box-shadow: 0 8px 32px rgba(0,0,0,0.4), inset 0 1px 0 rgba(255,255,255,0.05);
        }
        .logo {
            width: 48px; height: 48px; margin: 0 auto 16px;
            background: linear-gradient(135deg, #00a1d6, #764ba2);
            border-radius: 14px; display: flex; align-items: center; justify-content: center;
            font-size: 20px; box-shadow: 0 4px 20px rgba(0,161,214,0.3);
        }
        h1 { font-size: 20px; font-weight: 600; color: #fff; margin-bottom: 4px; }
        .subtitle { color: rgba(255,255,255,0.3); font-size: 12px; margin-bottom: 28px; }
        .status-section {
            background: rgba(255,255,255,0.03);
            border: 1px solid rgba(255,255,255,0.05);
            border-radius: 14px; padding: 16px; margin-bottom: 24px;
            min-height: 64px; display: flex; flex-direction: column;
            align-items: center; justify-content: center;
        }
        .status-text { font-size: 13px; color: rgba(255,255,255,0.5); display: flex; align-items: center; gap: 8px; }
        .status-text.success { color: #4ade80; }
        .status-text.error { color: #f87171; }
        .user-tag {
            display: inline-flex; align-items: center; gap: 6px; margin-top: 8px;
            padding: 4px 12px; background: rgba(0,161,214,0.1);
            border: 1px solid rgba(0,161,214,0.2); border-radius: 16px;
            font-size: 11px; color: #00a1d6; font-family: "SF Mono", "Fira Code", monospace;
        }
        .actions { display: flex; flex-direction: column; gap: 10px; }
        .btn {
            width: 100%; padding: 12px 20px; font-size: 13px; font-weight: 500;
            border: none; border-radius: 10px; cursor: pointer; transition: all 0.2s ease;
            color: #fff; background: linear-gradient(135deg, #00a1d6 0%, #0088cc 100%);
            box-shadow: 0 4px 16px rgba(0,161,214,0.3);
        }
        .btn:hover { transform: translateY(-1px); box-shadow: 0 6px 24px rgba(0,161,214,0.4); }
        .btn:active { transform: translateY(0); }
        .btn:disabled { background: rgba(255,255,255,0.08); cursor: not-allowed; transform: none; box-shadow: none; color: rgba(255,255,255,0.3); }
        .btn-secondary { background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.1); box-shadow: none; }
        .btn-secondary:hover { background: rgba(255,255,255,0.1); box-shadow: 0 4px 16px rgba(0,0,0,0.2); }
        .spinner { width: 14px; height: 14px; border: 2px solid rgba(255,255,255,0.12); border-top-color: #00a1d6; border-radius: 50%; animation: spin 0.7s linear infinite; }
        @keyframes spin { to { transform: rotate(360deg); } }
        .hidden { display: none !important; }
        .copy-section {
            background: rgba(255,255,255,0.03);
            border: 1px solid rgba(0,161,214,0.15);
            border-radius: 14px; padding: 16px; margin-bottom: 24px; text-align: left;
        }
        .copy-header { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }
        .copy-icon {
            width: 24px; height: 24px;
            background: linear-gradient(135deg, #764ba2, #00a1d6);
            border-radius: 6px; display: flex; align-items: center;
            justify-content: center; font-size: 10px; font-weight: 600; color: #fff;
        }
        .copy-stitle { font-size: 13px; font-weight: 500; color: rgba(255,255,255,0.75); }
        .copy-body {
            font-size: 12.5px; color: rgba(255,255,255,0.6); line-height: 1.7;
            white-space: pre-wrap; max-height: 360px; overflow-y: auto;
            padding: 10px; background: rgba(0,0,0,0.2); border-radius: 8px;
        }
        .copy-body::-webkit-scrollbar { width: 4px; }
        .copy-body::-webkit-scrollbar-track { background: transparent; }
        .copy-body::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.08); border-radius: 2px; }
        .clear-btn {
            position: fixed; top: 16px; left: 400px; z-index: 10;
            padding: 6px 12px; font-size: 10px; font-weight: 500;
            border: 1px solid rgba(255,255,255,0.08); border-radius: 6px;
            cursor: pointer; transition: all 0.2s;
            color: rgba(255,255,255,0.25); background: rgba(255,255,255,0.02);
            backdrop-filter: blur(10px);
        }
        .clear-btn:hover { color: #f87171; border-color: rgba(248,113,113,0.3); background: rgba(248,113,113,0.06); }

        /* 模型选择器 */
        .model-btn {
            position: fixed; top: 16px; right: 16px; z-index: 10;
            padding: 6px 10px; font-size: 11px; font-weight: 500;
            border: 1px solid rgba(255,255,255,0.1); border-radius: 8px;
            cursor: pointer; transition: all 0.2s;
            color: rgba(255,255,255,0.5); background: rgba(255,255,255,0.04);
            backdrop-filter: blur(10px); display: flex; align-items: center; gap: 5px;
        }
        .model-btn:hover { color: #00a1d6; border-color: rgba(0,161,214,0.3); background: rgba(0,161,214,0.08); }
        .model-dot { width: 6px; height: 6px; border-radius: 50%; display: inline-block; }
        .model-dot.online { background: #4ade80; }
        .model-dot.offline { background: rgba(255,255,255,0.15); }

        .model-panel {
            position: fixed; top: 46px; right: 16px; z-index: 10;
            width: 280px;
            background: rgba(20,20,35,0.95); backdrop-filter: blur(20px);
            border: 1px solid rgba(255,255,255,0.08); border-radius: 12px;
            padding: 12px;
            display: none; box-shadow: 0 8px 32px rgba(0,0,0,0.5);
        }
        .model-panel.show { display: block; }
        .model-panel .mp-title { font-size: 10px; color: rgba(255,255,255,0.3); margin-bottom: 8px; letter-spacing: 0.5px; }
        .model-option {
            display: flex; align-items: center; gap: 8px;
            padding: 8px 10px; border-radius: 8px; cursor: pointer;
            font-size: 12px; color: rgba(255,255,255,0.6); transition: all 0.15s;
            border: 1px solid transparent; margin-bottom: 3px;
        }
        .model-option:hover { background: rgba(255,255,255,0.04); }
        .model-option.active { background: rgba(0,161,214,0.1); border-color: rgba(0,161,214,0.2); color: #00a1d6; }
        .model-option .mo-name { flex: 1; }
        .model-option .mo-model { font-size: 10px; color: rgba(255,255,255,0.25); }
        .model-option .mo-check { color: #4ade80; display: none; }
        .model-option.active .mo-check { display: inline; }
        .model-option input { display: none; }
        /* 内联配置区 */
        .model-config {
            padding: 8px 10px; margin: 4px 0 6px;
            background: rgba(0,0,0,0.2); border-radius: 8px;
            display: none;
        }
        .model-config.show { display: block; }
        .model-config input {
            width: 100%; padding: 5px 8px; margin-bottom: 5px;
            background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.08);
            border-radius: 5px; color: rgba(255,255,255,0.7); font-size: 11px;
            outline: none; box-sizing: border-box;
        }
        .model-config input:focus { border-color: rgba(0,161,214,0.4); }
        .model-config .mc-actions { display: flex; gap: 4px; }
        .model-config .mc-btn {
            flex: 1; padding: 4px 0; font-size: 10px; font-weight: 500;
            border: 1px solid rgba(255,255,255,0.08); border-radius: 5px;
            cursor: pointer; transition: all 0.15s; text-align: center;
            color: rgba(255,255,255,0.5); background: rgba(255,255,255,0.04);
        }
        .model-config .mc-btn:hover { color: #00a1d6; border-color: rgba(0,161,214,0.3); background: rgba(0,161,214,0.08); }
        .model-config .mc-btn.save { color: #4ade80; border-color: rgba(74,222,128,0.3); }
        .model-config .mc-btn.save:hover { background: rgba(74,222,128,0.1); }

        .footer { text-align: center; margin-top: 16px; font-size: 10px; color: rgba(255,255,255,0.12); }
    </style>
</head>
<body>
    <div class="sidebar" id="sidebar">
        <div class="sidebar-header">
            <span>COLLECTION</span>
            <label class="sidebar-toggle hidden" id="privateToggle">
                <input type="checkbox" id="showPrivate" onchange="renderVideos();showCopy();"> 私密
            </label>
        </div>
        <div class="liked-section" id="likedSection">
            <div class="liked-header" onclick="toggleLiked()">
                <span class="arrow">&#9654;</span>
                <span>近期动向</span>
                <span id="likedCount" style="font-weight:400;color:rgba(255,255,255,0.15)"></span>
            </div>
            <div class="liked-body" id="likedBody">
                <div class="liked-empty">暂无数据</div>
            </div>
        </div>
        <div class="sidebar-list" id="videoList">
            <div class="sidebar-empty">等待采集数据...</div>
        </div>
    </div>
    <div class="main">
        <button class="clear-btn hidden" id="clearBtn" onclick="doSwitch()">Clear Data</button>
        <button class="model-btn" id="modelBtn" onclick="toggleModelPanel()">
            <span class="model-dot" id="modelDot"></span>
            <span id="modelLabel">Model</span>
        </button>
        <div class="model-panel" id="modelPanel"></div>
        <div class="card">
            <div class="logo">B</div>
            <h1>BiliCollector</h1>
            <p class="subtitle">Bilibili data collector &amp; copywriter</p>

            <div class="status-section">
                <div id="status" class="status-text">
                    <div class="spinner"></div>
                    Checking login status...
                </div>
                <div id="userInfo" class="user-tag hidden"></div>
            </div>

            <div id="copySection" class="copy-section hidden">
                <div class="copy-header">
                    <div class="copy-icon">W</div>
                    <span id="copyTitle" class="copy-stitle">文案</span>
                </div>
                <div id="copyContent" class="copy-body"></div>
            </div>

            <div class="actions">
                <button id="loginBtn" class="btn hidden" onclick="doLogin()">Login Bilibili</button>
                <button id="collectBtn" class="btn hidden" onclick="doCollect()">Start Collection</button>
                <button id="analyzeBtn" class="btn btn-secondary hidden" onclick="doAnalyze()">Generate Report</button>
                <button id="copyBtn" class="btn btn-secondary hidden" onclick="doCopy()">Generate Copy</button>
                <button id="retryBtn" class="btn btn-secondary hidden" onclick="doCollect()">Retry</button>
                <button id="switchBtn" class="btn btn-secondary hidden" onclick="doSwitch()">Switch Account</button>
            </div>
        </div>
        <div class="footer">All processing done locally</div>
    </div>

    <script>
        let pollTimer = null;

        function renderVideos() {
            fetch('/api/videos')
                .then(r => r.json())
                .then(d => {
                    const vl = document.getElementById('videoList');
                    const months = d.months || {};
                    const keys = Object.keys(months);
                    if (keys.length === 0) {
                        vl.innerHTML = '<div class="sidebar-empty">暂无视频数据</div>';
                        return;
                    }
                    const showPrivate = document.getElementById('showPrivate').checked;
                    let html = '';
                    for (const month of keys) {
                        let videos = months[month];
                        if (!videos || videos.length === 0) continue;
                        // 过滤私密视频
                        if (!showPrivate) {
                            videos = videos.filter(v => !v.is_private);
                        }
                        if (videos.length === 0) continue;
                        let cntLabel = showPrivate ? videos.length : videos.length;
                        html += '<div class="month-group">';
                        html += '<div class="month-header">' + month + ' &middot; ' + cntLabel + '</div>';
                        for (const v of videos) {
                            const link = v.link || 'https://www.bilibili.com/video/' + (v.bvid || '');
                            const plays = v.plays || '';
                            let title = v.title || '?';
                            if (v.is_private) title += ' ***';
                            html += '<a class="video-item" href="' + link + '" target="_blank" title="' + title + '">';
                            html += '<span class="v-title">' + title + '</span>';
                            html += '<span class="v-plays">' + plays + '</span>';
                            html += '<span class="v-link-icon">&#8599;</span>';
                            html += '</a>';
                        }
                        html += '</div>';
                    }
                    vl.innerHTML = html;
                })
                .catch(() => {});
        }

        function toggleLiked() {
            const body = document.getElementById('likedBody');
            const arrow = document.querySelector('.liked-header .arrow');
            body.classList.toggle('open');
            arrow.classList.toggle('open');
        }

        function renderLikedVideos() {
            fetch('/api/liked_videos')
                .then(r => r.json())
                .then(d => {
                    const body = document.getElementById('likedBody');
                    const cnt = document.getElementById('likedCount');
                    const list = d.list || [];
                    if (list.length === 0) {
                        body.innerHTML = '<div class="liked-empty">暂无数据</div>';
                        cnt.textContent = '';
                        return;
                    }
                    cnt.textContent = list.length;
                    let html = '';
                    for (const v of list) {
                        const tags = (v.tags || []).map(t => '<span class="li-tag">#' + t + '</span>').join('');
                        html += '<div class="liked-item">';
                        html += '<a class="li-title" href="https://www.bilibili.com/video/' + v.bvid + '" target="_blank">' + v.title + '</a>';
                        html += '<div class="li-tags">' + tags + '</div>';
                        html += '</div>';
                    }
                    body.innerHTML = html;
                })
                .catch(() => {});
        }

        function updateUI(data) {
            const st = document.getElementById('status');
            const ui = document.getElementById('userInfo');
            const lb = document.getElementById('loginBtn');
            const cb = document.getElementById('collectBtn');
            const ab = document.getElementById('analyzeBtn');
            const cpb = document.getElementById('copyBtn');
            const rb = document.getElementById('retryBtn');
            const clr = document.getElementById('clearBtn');
            const sb = document.getElementById('switchBtn');

            [lb, cb, ab, cpb, rb, sb].forEach(b => b.classList.add('hidden'));
            clr.classList.add('hidden');

            switch(data.status) {
                case 'checking':
                    st.innerHTML = '<div class="spinner"></div>Checking login status...';
                    break;
                case 'need_login':
                    st.textContent = 'Not logged in';
                    lb.classList.remove('hidden');
                    break;
                case 'logged_in':
                    st.textContent = 'Ready to collect';
                    st.className = 'status-text success';
                    ui.textContent = 'UID: ' + data.uid; ui.classList.remove('hidden');
                    clr.classList.remove('hidden'); cb.classList.remove('hidden'); sb.classList.remove('hidden');
                    break;
                case 'collecting':
                    st.innerHTML = '<div class="spinner"></div>Collecting data...';
                    sb.classList.remove('hidden');
                    break;
                case 'done':
                    st.textContent = 'Collection done';
                    st.className = 'status-text success';
                    ui.textContent = 'UID: ' + data.uid; ui.classList.remove('hidden');
                    clr.classList.remove('hidden'); ab.classList.remove('hidden'); rb.classList.remove('hidden'); sb.classList.remove('hidden');
                    renderVideos(); renderLikedVideos();
                    break;
                case 'analyzed':
                    st.textContent = data.message;
                    st.className = 'status-text success';
                    ui.textContent = 'UID: ' + data.uid; ui.classList.remove('hidden');
                    clr.classList.remove('hidden'); cpb.classList.remove('hidden'); rb.classList.remove('hidden'); sb.classList.remove('hidden');
                    renderLikedVideos();
                    break;
                case 'generating':
                    st.innerHTML = '<div class="spinner"></div>Generating copy...';
                    sb.classList.remove('hidden');
                    break;
                case 'copy_done':
                    st.textContent = data.message;
                    st.className = 'status-text success';
                    ui.textContent = 'UID: ' + data.uid; ui.classList.remove('hidden');
                    clr.classList.remove('hidden'); rb.classList.remove('hidden'); sb.classList.remove('hidden');
                    document.getElementById('privateToggle').classList.remove('hidden');
                    showCopy(); renderLikedVideos();
                    break;
                case 'error':
                    st.textContent = data.message;
                    st.className = 'status-text error';
                    rb.classList.remove('hidden'); sb.classList.remove('hidden');
                    break;
            }
        }

        function showCopy() {
            const isPrivate = document.getElementById('showPrivate').checked;
            const url = '/api/copy_result' + (isPrivate ? '?private=1' : '');
            fetch(url)
                .then(r => r.json())
                .then(d => {
                    if (d.result) {
                        document.getElementById('copyTitle').textContent = (isPrivate ? '[私密] ' : '') + (d.title || '文案');
                        document.getElementById('copyContent').textContent = d.content || JSON.stringify(d.result, null, 2);
                        document.getElementById('copySection').classList.remove('hidden');
                    }
                });
        }

        function doLogin() { fetch('/api/login', {method:'POST'}).then(r=>r.json()).then(d=>{if(d.status==='ok')pollStatus()}) }
        function doCollect() { fetch('/api/collect', {method:'POST'}).then(r=>r.json()).then(d=>pollStatus()) }
        function doAnalyze() { fetch('/api/analyze', {method:'POST'}).then(r=>r.json()).then(d=>pollStatus()) }
        function doCopy() { fetch('/api/generate_copy', {method:'POST'}).then(r=>r.json()).then(d=>pollStatus()) }
        function doSwitch() {
            document.getElementById('copySection').classList.add('hidden');
            fetch('/api/switch_account', {method:'POST'}).then(r=>r.json()).then(d => {
                window.location.reload();
            });
        }

        function pollStatus() {
            if (pollTimer) clearInterval(pollTimer);
            pollTimer = setInterval(() => {
                fetch('/api/status').then(r=>r.json()).then(d => {
                    updateUI(d);
                    if (['done','analyzed','copy_done','error','logged_in'].includes(d.status))
                        clearInterval(pollTimer);
                }).catch(() => {});
            }, 1000);
        }

        // ── 模型选择器 ──
        function toggleModelPanel() {
            const p = document.getElementById('modelPanel');
            p.classList.toggle('show');
            if (p.classList.contains('show')) loadModelStatus();
        }

        function loadModelStatus() {
            fetch('/api/llm_status').then(r=>r.json()).then(d => {
                const p = document.getElementById('modelPanel');
                let html = '<div class="mp-title">MODEL PROVIDER</div>';
                for (const prov of d.providers || []) {
                    if (prov.key === 'auto') continue;
                    const active = prov.key === d.current ? ' active' : '';
                    const online = prov.online ? 'online' : 'offline';
                    const check = active ? '&#10003;' : '';
                    html += '<div class="model-option' + active + '" data-prov="' + prov.key + '">';
                    html += '<span class="model-dot ' + online + '"></span>';
                    html += '<span class="mo-name">' + prov.name + '</span>';
                    html += '<span class="mo-model">' + (prov.model || '') + '</span>';
                    html += '<span class="mo-check">' + check + '</span>';
                    html += '</div>';
                    // 配置面板（默认对当前 provider 展开）
                    const showCfg = prov.key === d.current && prov.key !== 'ollama' ? ' show' : '';
                    html += '<div class="model-config' + showCfg + '" data-cfg="' + prov.key + '">';
                    html += '<input class="mc-key" placeholder="API Key" value="' + (prov.has_key ? '••••••••' : '') + '">';
                    html += '<input class="mc-model" placeholder="Model name" value="' + (prov.model || '') + '">';
                    html += '<div class="mc-actions">';
                    html += '<span class="mc-btn" onclick="saveModelConfig(\\'' + prov.key + '\\')">&#10003; Save</span>';
                    html += '</div></div>';
                }
                p.innerHTML = html;
                document.getElementById('modelLabel').textContent = d.current || 'auto';
                document.getElementById('modelDot').className = 'model-dot ' + (d.current !== 'auto' ? 'online' : 'offline');
            }).catch(() => {});
        }

        function saveModelConfig(provider) {
            const panel = document.getElementById('modelPanel');
            const keyInput = panel.querySelector('.model-config[data-cfg="' + provider + '"] .mc-key');
            const modelInput = panel.querySelector('.model-config[data-cfg="' + provider + '"] .mc-model');
            fetch('/api/llm_switch', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    provider: provider,
                    api_key: keyInput && keyInput.value && !keyInput.value.includes('••') ? keyInput.value : undefined,
                    model: modelInput ? modelInput.value : undefined,
                }),
            }).then(r => r.json()).then(d => {
                panel.classList.remove('show');
                document.getElementById('modelLabel').textContent = provider;
                document.getElementById('modelDot').className = 'model-dot online';
                // 刷新状态
                setTimeout(loadModelStatus, 500);
            });
        }

        // 点击面板外关闭
        document.addEventListener('click', function(e) {
            const btn = document.getElementById('modelBtn');
            const panel = document.getElementById('modelPanel');
            const opt = e.target.closest('.model-option');
            if (opt) {
                // 展开对应配置区
                const prov = opt.dataset.prov;
                panel.querySelectorAll('.model-config').forEach(c => c.classList.remove('show'));
                const cfg = panel.querySelector('.model-config[data-cfg="' + prov + '"]');
                if (cfg && prov !== 'ollama') cfg.classList.add('show');
                // 高亮
                panel.querySelectorAll('.model-option').forEach(o => o.classList.remove('active'));
                opt.classList.add('active');
                return;
            }
            if (!btn.contains(e.target) && !panel.contains(e.target)) {
                panel.classList.remove('show');
            }
        });

        loadModelStatus();

        fetch('/api/status').then(r=>r.json()).then(d => {
            updateUI(d);
            if (['checking','collecting','generating'].includes(d.status)) pollStatus();
            if (d.status === 'copy_done') showCopy();
        }).catch(e => {
            document.getElementById('status').innerHTML = '<span style="color:#f87171">Connection failed: ' + e.message + '</span><br><span style="font-size:11px;color:rgba(255,255,255,0.3)">Make sure the server is running on port 18234</span>';
        });
    </script>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.end_headers()
            self.wfile.write(HTML.encode("utf-8"))
        elif self.path == "/api/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(app_state, ensure_ascii=False).encode("utf-8"))
        elif self.path.startswith("/api/copy_result"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            is_private = "private=1" in self.path
            uid = app_state.get("uid", "")
            if is_private:
                priv_path = BILI_FAV_HOME / f"copy_{uid}_private.json"
                try:
                    r = json.loads(priv_path.read_text("utf-8"))
                except Exception:
                    r = None
            else:
                r = app_state.get("copy_result")
                if not r:
                    pub_path = BILI_FAV_HOME / f"copy_{uid}.json"
                    try:
                        r = json.loads(pub_path.read_text("utf-8"))
                    except Exception:
                        r = None
            if r:
                labels = r.get("labels", [])
                title = f'你的成分是{"|".join(f"\"{l}\"" for l in labels)}' if labels else r.get("title", "文案结果")
                resp = {"result": r, "title": title, "content": r.get("content", "")}
            else:
                resp = {"result": None}
            self.wfile.write(json.dumps(resp, ensure_ascii=False).encode("utf-8"))
        elif self.path == "/api/videos":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            uid = app_state.get("uid", "")
            months = load_videos_grouped(uid) if uid else {}
            self.wfile.write(json.dumps({"months": months}, ensure_ascii=False).encode("utf-8"))
        elif self.path == "/api/liked_videos":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            uid = app_state.get("uid", "")
            liked = []
            if uid:
                liked_path = BILI_FAV_HOME / f"data_{uid}" / "liked_videos.json"
                try:
                    liked = json.loads(liked_path.read_text("utf-8"))
                except Exception:
                    liked = []
            self.wfile.write(json.dumps({"list": liked}, ensure_ascii=False).encode("utf-8"))
        elif self.path == "/api/llm_status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            try:
                import llm_config as llm
                cfg = llm.resolve_config()
                p = cfg.get("provider", "auto")
                model = llm.current_model_name()
                providers = []
                for k in ("ollama", "deepseek", "siliconflow", "openai"):
                    pc = cfg.get(k, {})
                    prov = {"key": k, "name": k.capitalize(), "model": pc.get("model", ""), "has_key": bool(pc.get("api_key", ""))}
                    if k == "ollama":
                        ok, _ = llm.check_ollama(cfg["ollama"]["host"])
                        prov["online"] = ok
                    else:
                        prov["online"] = bool(pc.get("api_key", ""))
                    providers.append(prov)
                # custom
                cc = cfg.get("custom", {})
                providers.append({"key": "custom", "name": "Custom", "model": cc.get("model", ""), "has_key": bool(cc.get("api_key", "")), "online": bool(cc.get("api_key", ""))})
                # auto
                providers.append({"key": "auto", "name": "Auto", "model": "", "has_key": False, "online": False})
                self.wfile.write(json.dumps({"current": p, "model": model, "providers": providers}, ensure_ascii=False).encode("utf-8"))
            except Exception as e:
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/api/login":
            if app_state["status"] in ("collecting",):
                self._json({"status": "error", "message": "Busy"})
                return
            app_state["status"] = "checking"
            app_state["message"] = "Opening browser..."
            threading.Thread(target=do_login, daemon=True).start()
            self._json({"status": "ok"})

        elif self.path == "/api/collect":
            if app_state["status"] == "collecting":
                self._json({"status": "error", "message": "Already collecting"})
                return
            app_state["status"] = "collecting"
            app_state["message"] = "Collecting..."
            threading.Thread(target=do_collect, daemon=True).start()
            self._json({"status": "ok"})

        elif self.path == "/api/analyze":
            if app_state["status"] in ("collecting", "analyzing"):
                self._json({"status": "error", "message": "Busy"})
                return
            app_state["status"] = "analyzing"
            app_state["message"] = "Generating report..."
            threading.Thread(target=do_analyze, daemon=True).start()
            self._json({"status": "ok"})

        elif self.path == "/api/generate_copy":
            if app_state["status"] in ("generating",):
                self._json({"status": "error", "message": "Busy"})
                return
            app_state["status"] = "generating"
            app_state["message"] = "Generating copy..."
            threading.Thread(target=do_generate_copy, daemon=True).start()
            self._json({"status": "ok"})

        elif self.path == "/api/switch_account":
            do_switch_account()
            self._json({"status": "ok"})

        elif self.path == "/api/llm_switch":
            import llm_config as llm
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl)) if cl else {}
            provider = body.get("provider", "")
            cfg = llm.load_config()
            cfg["provider"] = provider
            if provider in ("deepseek", "siliconflow", "openai", "custom"):
                pc = cfg.setdefault(provider, {})
                if body.get("api_key"):
                    pc["api_key"] = body["api_key"]
                if body.get("model"):
                    pc["model"] = body["model"]
                if body.get("api_base"):
                    pc["api_base"] = body["api_base"]
            llm.save_config(cfg)
            self._json({"status": "ok", "provider": provider})

        elif self.path == "/api/receive_result":
            # 保留机 C 回传接口（兼容，但不再主动拉取）
            import re
            ct = self.headers.get("Content-Type", "")
            cl = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(cl)
            m = re.search(r"boundary=([^;]+)", ct)
            ok = False
            if m:
                for part in body.split(("--" + m.group(1)).encode()):
                    if b"Content-Disposition" not in part:
                        continue
                    blank = part.find(b"\r\n\r\n")
                    if blank < 0:
                        continue
                    data = part[blank+4:].rstrip(b"\r\n- ")
                    if b'name="file"' in part[:blank]:
                        try:
                            result = json.loads(data.decode("utf-8"))
                            app_state["copy_result"] = result
                            app_state["copy_title"] = result.get("title", "文案结果")
                            app_state["status"] = "copy_done"
                            app_state["message"] = "文案结果已收到"
                            ok = True
                        except json.JSONDecodeError:
                            pass
            self._json({"status": "ok" if ok else "failed"})

        else:
            self.send_response(404)
            self.end_headers()

    def _json(self, data):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))

    def log_message(self, *a):
        pass


def main():
    import argparse

    parser = argparse.ArgumentParser(description="BiliCollector — B站数据采集与文案生成")
    parser.add_argument("--send-url", type=str, default=os.environ.get("DEST_URL", ""),
                        help="可选：报告同时发送到文案机")
    args = parser.parse_args()

    if args.send_url:
        app_state["dest_url"] = args.send_url
        print(f"  发送目标: {args.send_url}")

    uid = check_login()
    if uid:
        app_state["uid"] = uid
        app_state["status"] = "logged_in"
        app_state["message"] = "Logged in"
    else:
        app_state["status"] = "need_login"

    port = 18234
    server = HTTPServer(("0.0.0.0", port), Handler)

    print(f"\n  http://127.0.0.1:{port}")
    print()
    print("  流程: 登录 -> 采集 -> Generate Report -> Generate Copy")
    if app_state["dest_url"]:
        print(f"  报告同时发往: {app_state['dest_url']}")
    print("  Press Ctrl+C to exit\n")

    threading.Timer(0.5, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nBye")
        server.server_close()


if __name__ == "__main__":
    main()
