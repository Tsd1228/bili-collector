#!/usr/bin/env python3
"""
B站报告接收端 — 在文案生成机（机 C）上运行

监听 HTTP POST，接收来自机 B 的分析报告，保存到 inbox 目录。

用法：
  python recv.py
  python recv.py --port 18236
  python recv.py --dir "C:/path/to/inbox"
"""

import os
import re
import sys
import tempfile
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs


INBOX = os.environ.get("REPORT_INBOX", "./inbox")


def parse_multipart(body: bytes, boundary: bytes) -> dict | None:
    """简陋版 multipart/form-data 解析，只提取第一个 file 字段"""
    parts = body.split(b"--" + boundary)
    for part in parts:
        if b"Content-Disposition" not in part:
            continue
        # 找空行（header 和 body 的分隔）
        blank = part.find(b"\r\n\r\n")
        if blank == -1:
            continue
        headers_raw = part[:blank].decode("utf-8", errors="replace")
        file_data = part[blank + 4 :]
        # 去掉末尾的 \r\n--
        file_data = file_data.rstrip(b"\r\n- ")

        # 检查是不是 file 字段
        if 'name="file"' in headers_raw:
            # 提取文件名
            m = re.search(r'filename="([^"]*)"', headers_raw)
            filename = m.group(1) if m else "report.txt"
            return {"filename": filename, "data": file_data}
    return None


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_type = self.headers.get("Content-Type", "")
        content_length = int(self.headers.get("Content-Length", 0))

        # 提取 boundary
        m = re.search(r"boundary=([^;]+)", content_type)
        if not m:
            self._respond(400, "NO BOUNDARY")
            return

        boundary = m.group(1).encode("utf-8")
        body = self.rfile.read(content_length)
        result = parse_multipart(body, boundary)

        if result and result["data"]:
            dest = Path(INBOX)
            dest.mkdir(parents=True, exist_ok=True)
            filepath = dest / result["filename"]
            filepath.write_bytes(result["data"])
            print(f"\n[接收] {result['filename']} ({len(result['data'])} bytes) -> {filepath}")
            self._respond(200, "OK")
        else:
            self._respond(400, "NO FILE")

    def do_GET(self):
        self._respond(200, "Report receiver running. Send POST with file field.")

    def _respond(self, code: int, text: str):
        self.send_response(code)
        self.end_headers()
        self.wfile.write(text.encode("utf-8"))

    def log_message(self, fmt, *args):
        pass


def main():
    port = int(os.environ.get("RECV_PORT", 18236))
    if len(sys.argv) > 1:
        for i, arg in enumerate(sys.argv[1:]):
            if arg == "--port" and i + 2 < len(sys.argv):
                port = int(sys.argv[i + 2])
            elif arg == "--dir" and i + 2 < len(sys.argv):
                global INBOX
                INBOX = sys.argv[i + 2]

    print(f"[启动] 监听 :{port}")
    print(f"[目录] {INBOX}")
    print(f"[用法] 机 B 执行: python submit_client.py --send-url http://本机IP:{port}/")
    print()

    server = HTTPServer(("0.0.0.0", port), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[退出]")
        server.server_close()


if __name__ == "__main__":
    main()
