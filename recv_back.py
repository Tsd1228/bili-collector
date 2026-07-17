#!/usr/bin/env python3
"""
机 B 接收端 — 接收机 C 返回的文案生成结果

用法：
  python recv_back.py
  python recv_back.py --port 18237
"""

import os, re, sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

OUTBOX = Path(__file__).parent / "outbox"

class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        ct = self.headers.get("Content-Type", "")
        cl = int(self.headers.get("Content-Length", 0))
        m = re.search(r"boundary=([^;]+)", ct)
        if not m:
            return self._r(400, b"NO BOUNDARY")
        for part in self.rfile.read(cl).split(("--" + m.group(1)).encode()):
            if b"Content-Disposition" not in part:
                continue
            blank = part.find(b"\r\n\r\n")
            if blank < 0:
                continue
            data = part[blank + 4 :].rstrip(b"\r\n- ")
            if b'name="file"' in part[:blank]:
                OUTBOX.mkdir(parents=True, exist_ok=True)
                fpath = OUTBOX / "result.json"
                fpath.write_bytes(data)
                print(f"\n[接收] 文案结果 -> {fpath} ({len(data)} bytes)")
                return self._r(200, b"OK")
        self._r(400, b"NO FILE")
    def _r(self, c, b):
        self.send_response(c)
        self.end_headers()
        self.wfile.write(b)
    def log_message(self, *a): pass

if __name__ == "__main__":
    port = int(os.environ.get("RECV_BACK_PORT", 18237))
    if len(sys.argv) > 2 and sys.argv[1] == "--port":
        port = int(sys.argv[2])
    print(f"[启动] 监听 :{port}，接收目录: {OUTBOX.resolve()}")
    HTTPServer(("0.0.0.0", port), Handler).serve_forever()
