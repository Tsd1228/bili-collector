#!/usr/bin/env python3
"""
B站数据采集 — Web 界面版

双击运行，自动打开浏览器，用户只需：
1. 点击「登录」→ 扫码
2. 等待采集完成
"""

import json
import threading
import webbrowser
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.parse
import sys
import os

sys.path.insert(0, str(Path(__file__).parent))

BILI_FAV_HOME = Path.home() / ".bilibili_fav"
UID_FILE = BILI_FAV_HOME / "bili_uid.txt"

# 状态
app_state = {
    "uid": None,
    "status": "checking",  # checking / need_login / logged_in / collecting / done / error
    "message": "",
    "total_videos": 0,
}


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
        from bili_common import do_login as _do_login
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            uid = _do_login(p)
        app_state["uid"] = uid
        app_state["status"] = "logged_in"
        app_state["message"] = "登录成功"
    except Exception as e:
        app_state["status"] = "error"
        app_state["message"] = str(e)


def do_collect():
    try:
        from bilbil import collect_favorites

        videos = collect_favorites(uid=app_state["uid"])
        total = sum(len(v) for v in videos) if videos else 0
        app_state["total_videos"] = total
        app_state["status"] = "done"
        app_state["message"] = f"采集完成，共 {total} 个视频"
    except Exception as e:
        app_state["status"] = "error"
        app_state["message"] = str(e)


HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>B站数据采集</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .card {
            background: white;
            border-radius: 20px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            padding: 50px 40px;
            width: 420px;
            text-align: center;
        }
        h1 {
            font-size: 28px;
            color: #333;
            margin-bottom: 10px;
        }
        .subtitle {
            color: #999;
            font-size: 14px;
            margin-bottom: 30px;
        }
        .status-box {
            background: #f8f9fa;
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 30px;
            min-height: 80px;
        }
        .status-text {
            font-size: 16px;
            color: #333;
        }
        .status-text.success { color: #28a745; }
        .status-text.error { color: #dc3545; }
        .user-info {
            font-size: 14px;
            color: #666;
            margin-top: 10px;
        }
        .btn {
            display: inline-block;
            padding: 14px 40px;
            font-size: 16px;
            font-weight: 600;
            border: none;
            border-radius: 10px;
            cursor: pointer;
            transition: all 0.3s;
            color: white;
            background: linear-gradient(135deg, #00a1d6 0%, #0091d5 100%);
        }
        .btn:hover { transform: translateY(-2px); box-shadow: 0 5px 20px rgba(0,161,214,0.4); }
        .btn:disabled { background: #ccc; cursor: not-allowed; transform: none; box-shadow: none; }
        .btn-secondary {
            background: linear-gradient(135deg, #28a745 0%, #218838 100%);
        }
        .spinner {
            display: inline-block;
            width: 20px;
            height: 20px;
            border: 3px solid #ddd;
            border-top-color: #00a1d6;
            border-radius: 50%;
            animation: spin 0.8s linear infinite;
            margin-right: 10px;
            vertical-align: middle;
        }
        @keyframes spin { to { transform: rotate(360deg); } }
        .hidden { display: none; }
    </style>
</head>
<body>
    <div class="card">
        <h1>B站数据采集</h1>
        <p class="subtitle">登录你的 B站账号，一键采集收藏夹数据</p>
        
        <div class="status-box">
            <div id="status" class="status-text">正在检测登录状态...</div>
            <div id="userInfo" class="user-info hidden"></div>
        </div>
        
        <div id="actions">
            <button id="loginBtn" class="btn hidden" onclick="doLogin()">登录 B站</button>
            <button id="collectBtn" class="btn hidden" onclick="doCollect()">开始采集</button>
            <button id="retryBtn" class="btn hidden" onclick="doCollect()">重新采集</button>
        </div>
    </div>

    <script>
        let pollTimer = null;

        function updateUI(data) {
            const status = document.getElementById('status');
            const userInfo = document.getElementById('userInfo');
            const loginBtn = document.getElementById('loginBtn');
            const collectBtn = document.getElementById('collectBtn');
            const retryBtn = document.getElementById('retryBtn');

            loginBtn.classList.add('hidden');
            collectBtn.classList.add('hidden');
            retryBtn.classList.add('hidden');

            switch(data.status) {
                case 'checking':
                    status.innerHTML = '<span class="spinner"></span>正在检测登录状态...';
                    break;
                case 'need_login':
                    status.textContent = '未登录，请点击下方按钮登录';
                    loginBtn.classList.remove('hidden');
                    break;
                case 'logged_in':
                    status.textContent = '已登录';
                    status.className = 'status-text success';
                    userInfo.textContent = 'UID: ' + data.uid;
                    userInfo.classList.remove('hidden');
                    collectBtn.classList.remove('hidden');
                    break;
                case 'collecting':
                    status.innerHTML = '<span class="spinner"></span>正在采集数据，请勿关闭...';
                    break;
                case 'done':
                    status.textContent = data.message;
                    status.className = 'status-text success';
                    userInfo.textContent = 'UID: ' + data.uid;
                    userInfo.classList.remove('hidden');
                    retryBtn.classList.remove('hidden');
                    retryBtn.textContent = '重新采集';
                    break;
                case 'error':
                    status.textContent = '错误: ' + data.message;
                    status.className = 'status-text error';
                    retryBtn.classList.remove('hidden');
                    retryBtn.textContent = '重试';
                    break;
            }
        }

        function doLogin() {
            fetch('/api/login', {method: 'POST'})
                .then(r => r.json())
                .then(data => {
                    if (data.status === 'ok') {
                        pollStatus();
                    } else {
                        alert('登录失败: ' + data.message);
                    }
                });
        }

        function doCollect() {
            fetch('/api/collect', {method: 'POST'})
                .then(r => r.json())
                .then(data => {
                    pollStatus();
                });
        }

        function pollStatus() {
            if (pollTimer) clearInterval(pollTimer);
            pollTimer = setInterval(() => {
                fetch('/api/status')
                    .then(r => r.json())
                    .then(data => {
                        updateUI(data);
                        if (['done', 'error', 'logged_in'].includes(data.status)) {
                            clearInterval(pollTimer);
                        }
                    });
            }, 1000);
        }

        // 初始加载
        fetch('/api/status')
            .then(r => r.json())
            .then(data => {
                updateUI(data);
                if (['checking', 'collecting'].includes(data.status)) {
                    pollStatus();
                }
            });
    </script>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML.encode("utf-8"))
        elif self.path == "/api/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(app_state).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/api/login":
            if app_state["status"] in ("collecting",):
                self._json_response({"status": "error", "message": "采集中，请稍后"})
                return

            app_state["status"] = "checking"
            app_state["message"] = "正在打开浏览器..."
            threading.Thread(target=do_login, daemon=True).start()
            self._json_response({"status": "ok"})

        elif self.path == "/api/collect":
            if app_state["status"] == "collecting":
                self._json_response({"status": "error", "message": "正在采集中"})
                return

            app_state["status"] = "collecting"
            app_state["message"] = "正在采集数据..."
            threading.Thread(target=do_collect, daemon=True).start()
            self._json_response({"status": "ok"})

        else:
            self.send_response(404)
            self.end_headers()

    def _json_response(self, data):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))

    def log_message(self, format, *args):
        pass  # 静默日志


def main():
    # 检查登录状态
    uid = check_login()
    if uid:
        app_state["uid"] = uid
        app_state["status"] = "logged_in"
        app_state["message"] = "已登录"
    else:
        app_state["status"] = "need_login"

    # 启动服务器
    port = 18234
    server = HTTPServer(("127.0.0.1", port), Handler)

    print(f"[OK] Server started: http://127.0.0.1:{port}")
    print("     Browser will open automatically")
    print("     Press Ctrl+C to exit\n")

    # 自动打开浏览器
    threading.Timer(0.5, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[EXIT] Bye")
        server.server_close()


if __name__ == "__main__":
    main()
