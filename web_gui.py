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

# 便携模式：默认在脚本同级目录
_base_dir = Path(__file__).parent.resolve()
if os.environ.get("BILI_PORTABLE", "1") == "0":
    _base_dir = Path.home() / ".bilibili_fav"

BILI_FAV_HOME = _base_dir
UID_FILE = BILI_FAV_HOME / "bili_uid.txt"

# 状态
app_state = {
    "uid": None,
    "status": "checking",
    "message": "",
    "total_videos": 0,
    "auto_close": False,
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
    try:
        from bilbil import collect_favorites

        videos = collect_favorites(uid=app_state["uid"])
        total = sum(len(v) for v in videos) if videos else 0
        app_state["total_videos"] = total
        app_state["status"] = "done"
        app_state["message"] = f"Done! {total} videos collected"
        
        if app_state["auto_close"]:
            import time
            time.sleep(1)
            import os
            os._exit(0)
    except Exception as e:
        app_state["status"] = "error"
        app_state["message"] = str(e)


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
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            overflow: hidden;
        }
        body::before {
            content: '';
            position: fixed;
            top: -50%;
            left: -50%;
            width: 200%;
            height: 200%;
            background: radial-gradient(circle at 30% 40%, rgba(0,161,214,0.08) 0%, transparent 50%),
                        radial-gradient(circle at 70% 60%, rgba(118,75,162,0.08) 0%, transparent 50%);
            animation: bgFloat 20s ease-in-out infinite;
        }
        @keyframes bgFloat {
            0%, 100% { transform: translate(0, 0); }
            50% { transform: translate(-2%, -2%); }
        }
        .container {
            position: relative;
            z-index: 1;
            width: 440px;
        }
        .card {
            background: rgba(255,255,255,0.03);
            backdrop-filter: blur(20px);
            border: 1px solid rgba(255,255,255,0.06);
            border-radius: 24px;
            padding: 48px 40px;
            text-align: center;
            box-shadow: 0 8px 32px rgba(0,0,0,0.4),
                        inset 0 1px 0 rgba(255,255,255,0.05);
        }
        .logo {
            width: 56px;
            height: 56px;
            margin: 0 auto 20px;
            background: linear-gradient(135deg, #00a1d6, #764ba2);
            border-radius: 16px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 24px;
            box-shadow: 0 4px 20px rgba(0,161,214,0.3);
        }
        h1 {
            font-size: 22px;
            font-weight: 600;
            color: #fff;
            letter-spacing: -0.5px;
            margin-bottom: 6px;
        }
        .subtitle {
            color: rgba(255,255,255,0.35);
            font-size: 13px;
            margin-bottom: 36px;
        }
        .status-section {
            background: rgba(255,255,255,0.03);
            border: 1px solid rgba(255,255,255,0.05);
            border-radius: 16px;
            padding: 20px;
            margin-bottom: 28px;
            min-height: 72px;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
        }
        .status-text {
            font-size: 14px;
            color: rgba(255,255,255,0.6);
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .status-text.success { color: #4ade80; }
        .status-text.error { color: #f87171; }
        .user-tag {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            margin-top: 10px;
            padding: 6px 14px;
            background: rgba(0,161,214,0.1);
            border: 1px solid rgba(0,161,214,0.2);
            border-radius: 20px;
            font-size: 12px;
            color: #00a1d6;
            font-family: "SF Mono", "Fira Code", monospace;
        }
        .actions {
            display: flex;
            flex-direction: column;
            gap: 12px;
        }
        .btn {
            position: relative;
            width: 100%;
            padding: 14px 24px;
            font-size: 14px;
            font-weight: 500;
            border: none;
            border-radius: 12px;
            cursor: pointer;
            transition: all 0.2s ease;
            color: #fff;
            background: linear-gradient(135deg, #00a1d6 0%, #0088cc 100%);
            box-shadow: 0 4px 16px rgba(0,161,214,0.3);
            letter-spacing: 0.3px;
        }
        .btn:hover {
            transform: translateY(-1px);
            box-shadow: 0 6px 24px rgba(0,161,214,0.4);
        }
        .btn:active {
            transform: translateY(0);
        }
        .btn:disabled {
            background: rgba(255,255,255,0.08);
            cursor: not-allowed;
            transform: none;
            box-shadow: none;
            color: rgba(255,255,255,0.3);
        }
        .btn-secondary {
            background: rgba(255,255,255,0.06);
            border: 1px solid rgba(255,255,255,0.1);
            box-shadow: none;
        }
        .btn-secondary:hover {
            background: rgba(255,255,255,0.1);
            box-shadow: 0 4px 16px rgba(0,0,0,0.2);
        }
        .spinner {
            width: 16px;
            height: 16px;
            border: 2px solid rgba(255,255,255,0.15);
            border-top-color: #00a1d6;
            border-radius: 50%;
            animation: spin 0.7s linear infinite;
        }
        @keyframes spin { to { transform: rotate(360deg); } }
        .hidden { display: none !important; }
        .checkbox-label {
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
            margin-top: 12px;
            font-size: 13px;
            color: rgba(255,255,255,0.5);
            cursor: pointer;
        }
        .checkbox-label input[type="checkbox"] {
            width: 16px;
            height: 16px;
            accent-color: #00a1d6;
        }
        .footer {
            text-align: center;
            margin-top: 20px;
            font-size: 11px;
            color: rgba(255,255,255,0.15);
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="card">
            <div class="logo">B</div>
            <h1>BiliCollector</h1>
            <p class="subtitle">Bilibili favorites &amp; dynamics collector</p>

            <div class="status-section">
                <div id="status" class="status-text">
                    <div class="spinner"></div>
                    Checking login status...
                </div>
                <div id="userInfo" class="user-tag hidden"></div>
            </div>

            <div class="actions">
                <button id="loginBtn" class="btn hidden" onclick="doLogin()">Login Bilibili</button>
                <button id="collectBtn" class="btn hidden" onclick="doCollect()">Start Collection</button>
                <button id="retryBtn" class="btn btn-secondary hidden" onclick="doCollect()">Retry</button>
                <label class="checkbox-label hidden" id="autoCloseLabel">
                    <input type="checkbox" id="autoCloseCheck" onchange="toggleAutoClose(this.checked)">
                    <span>采集完成后自动关闭程序</span>
                </label>
            </div>
        </div>
        <div class="footer">Data stored locally in program directory</div>
    </div>

    <script>
        let pollTimer = null;

        function toggleAutoClose(enabled) {
            fetch('/api/auto_close', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({enabled: enabled})
            });
        }

        function updateUI(data) {
            const status = document.getElementById('status');
            const userInfo = document.getElementById('userInfo');
            const loginBtn = document.getElementById('loginBtn');
            const collectBtn = document.getElementById('collectBtn');
            const retryBtn = document.getElementById('retryBtn');
            const autoCloseLabel = document.getElementById('autoCloseLabel');

            loginBtn.classList.add('hidden');
            collectBtn.classList.add('hidden');
            retryBtn.classList.add('hidden');
            autoCloseLabel.classList.add('hidden');

            switch(data.status) {
                case 'checking':
                    status.innerHTML = '<div class="spinner"></div>Checking login status...';
                    break;
                case 'need_login':
                    status.textContent = 'Not logged in';
                    loginBtn.classList.remove('hidden');
                    break;
                case 'logged_in':
                    status.textContent = 'Ready to collect';
                    status.className = 'status-text success';
                    userInfo.textContent = 'UID: ' + data.uid;
                    userInfo.classList.remove('hidden');
                    collectBtn.classList.remove('hidden');
                    autoCloseLabel.classList.remove('hidden');
                    break;
                case 'collecting':
                    status.innerHTML = '<div class="spinner"></div>Collecting data...';
                    status.className = 'status-text';
                    break;
                case 'done':
                    status.textContent = data.message;
                    status.className = 'status-text success';
                    userInfo.textContent = 'UID: ' + data.uid;
                    userInfo.classList.remove('hidden');
                    retryBtn.classList.remove('hidden');
                    break;
                case 'error':
                    status.textContent = data.message;
                    status.className = 'status-text error';
                    retryBtn.classList.remove('hidden');
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
                        alert(data.message);
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
                self._json_response({"status": "error", "message": "Collecting in progress"})
                return

            app_state["status"] = "checking"
            app_state["message"] = "Opening browser..."
            threading.Thread(target=do_login, daemon=True).start()
            self._json_response({"status": "ok"})

        elif self.path == "/api/collect":
            if app_state["status"] == "collecting":
                self._json_response({"status": "error", "message": "Already collecting"})
                return

            app_state["status"] = "collecting"
            app_state["message"] = "Collecting..."
            threading.Thread(target=do_collect, daemon=True).start()
            self._json_response({"status": "ok"})

        elif self.path == "/api/auto_close":
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            data = json.loads(body)
            app_state["auto_close"] = data.get("enabled", False)
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
        pass


def main():
    uid = check_login()
    if uid:
        app_state["uid"] = uid
        app_state["status"] = "logged_in"
        app_state["message"] = "Logged in"
    else:
        app_state["status"] = "need_login"

    port = 18234
    server = HTTPServer(("127.0.0.1", port), Handler)

    print(f"Server started: http://127.0.0.1:{port}")
    print("Browser will open automatically")
    print("Press Ctrl+C to exit\n")

    threading.Timer(0.5, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nBye")
        server.server_close()


if __name__ == "__main__":
    main()
