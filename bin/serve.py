#!/usr/bin/env python3
"""看板图床服务（轮播版）：监听 :8077。

- GET /quota.png → 轮播返回 pages/ 目录下的下一页（Kindle 每 5 分钟拉一次 = 5 分钟翻一页）
- GET /          → 浏览器预览页（也是同一轮播）
- GET /pages/<name> → 指定页（调试用）
- 访问日志写 server.log（记录每次请求的页面和来源 IP）
"""

import glob
import http.server
import os
import threading
import time

# 本文件在 <ROOT>/bin/ 下，运行数据统一放 <ROOT>/data/
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = os.path.join(ROOT, "data")
PAGES_DIR = os.path.join(BASE, "pages")
LOG = os.path.join(BASE, "server.log")

_counter = 0
_lock = threading.Lock()


# 轮播只包含四页正文（保留排除项，防止将来误把辅助图丢进 pages/）
EXCLUDE = {"status.png"}


def list_pages():
    return sorted(
        p for p in glob.glob(os.path.join(PAGES_DIR, "*.png"))
        if os.path.basename(p) not in EXCLUDE
    )


def next_page():
    global _counter
    pages = list_pages()
    if not pages:
        return None
    with _lock:
        page = pages[_counter % len(pages)]
        _counter += 1
    return page


def log(msg):
    with open(LOG, "a") as f:
        f.write(f"{time.strftime('%m/%d %H:%M:%S')} {msg}\n")


INDEX_HTML = b"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta http-equiv="refresh" content="300">
<style>html,body{margin:0;padding:0;background:#fff}img{display:block;width:100%;height:auto}</style>
</head><body><img src="quota.png" alt=""></body></html>
"""


class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        # /health 供 install.sh 与菜单栏自检：读完即走，不推进轮播、不写访问日志
        if self.path.startswith("/health"):
            body = b"ok\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.startswith("/quota.png"):
            page = next_page()
            if not page:
                self.send_error(404, "no pages rendered yet")
                return
            log(f"{self.client_address[0]} <- {os.path.basename(page)}")
            with open(page, "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path.startswith("/pages/"):
            name = os.path.basename(self.path)
            path = os.path.join(PAGES_DIR, name)
            if not os.path.isfile(path):
                self.send_error(404)
                return
            with open(path, "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(INDEX_HTML)))
            self.end_headers()
            self.wfile.write(INDEX_HTML)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        super().end_headers()

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    os.chdir(BASE)
    os.makedirs(PAGES_DIR, exist_ok=True)
    log("server start :8077")
    http.server.ThreadingHTTPServer(("0.0.0.0", 8077), Handler).serve_forever()
