#!/usr/bin/env python3
"""看板渲染调度：由 launchd 每 5 分钟调用。

职责：
  1. 判断现在要不要渲染（有私有 IP 即可；渲染是纯本地操作，不必按网段 gate）
  2. 依次跑四页渲染脚本（额度/待办/时间线每次刷，日程页 15 分钟内不重刷）
  3. 任一页失败不影响其他页

为什么用 Python：项目在 ~/Downloads 下，macOS TCC 会把 /bin/sh、/bin/bash
当作 "Platform Binary" 直接 Deny（exit 126），而 python3 不受此限。
"""

import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RENDER = os.path.join(ROOT, "render")
DATA = os.path.join(ROOT, "data")
PAGES = os.path.join(DATA, "pages")

PYTHON = sys.executable
# 配额页的共用模块目录（可选）：配置见 render/dash_paths.py
sys.path.insert(0, os.path.join(ROOT, "render"))
from dash_paths import WS  # noqa: E402
LOG = "/tmp/kindle-render.log"


def log(msg):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%m/%d %H:%M:%S')} {msg}\n")
    except OSError:
        pass


def local_ipv4():
    """返回 en1/en0 的 IPv4；都没有则空串。"""
    for iface in ("en1", "en0"):
        try:
            r = subprocess.run(["ipconfig", "getifaddr", iface],
                               capture_output=True, text=True, timeout=5)
            ip = (r.stdout or "").strip()
            if ip:
                return ip
        except Exception:
            continue
    return ""


def should_render():
    """有私有 IP 就渲染；回环/自分配/离线都跳过。"""
    ip = local_ipv4()
    if not ip or ip.startswith("127.") or ip.startswith("169.254."):
        log(f"skip: no private ip (ip={ip!r})")
        return False
    return True


def load_env():
    """把 Proma 工作区 .env 里的 key 注入环境（额度页需要）。"""
    path = os.path.join(WS, ".env")
    if not os.path.exists(path):
        log(f"warn: .env not found at {path}")
        return
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    except OSError as e:
        log(f"warn: read .env failed: {e}")


def run_page(script, out_name, extra_args=None):
    """跑一个渲染脚本；返回 True/False。"""
    out = os.path.join(PAGES, out_name)
    cmd = [PYTHON, os.path.join(RENDER, script), "--out", out]
    if extra_args:
        cmd.extend(extra_args)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180,
                           cwd=ROOT, env=os.environ.copy())
        if r.returncode == 0:
            msg = (r.stdout or "").strip().splitlines()
            log(f"ok {out_name}: {msg[-1] if msg else ''}")
            return True
        log(f"fail {out_name} rc={r.returncode}: {(r.stderr or '')[:200]}")
        return False
    except Exception as e:
        log(f"error {out_name}: {e}")
        return False


def main():
    if not should_render():
        return 0

    os.makedirs(PAGES, exist_ok=True)
    load_env()

    run_page("kindle_quota_render.py", "01-quota.png")
    run_page("render_todo.py", "03-todo.png")
    run_page("render_timeline.py", "04-timeline.png")

    # 日程页 15 分钟内不重刷：它较慢且变化不大
    sched = os.path.join(PAGES, "02-schedule.png")
    stale = (not os.path.exists(sched)) or (time.time() - os.path.getmtime(sched) > 900)
    if stale:
        run_page("render_schedule.py", "02-schedule.png")

    return 0


if __name__ == "__main__":
    sys.exit(main())
