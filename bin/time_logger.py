#!/usr/bin/env python3
"""时间采集器：launchd 每分钟调用，记录当前前台 App + 空闲状态。

为什么用 Python 而不是 shell：
项目位于 ~/Downloads 下，macOS 的 TCC 会把 /bin/sh、/bin/bash 当作
"Platform Binary" 直接 Deny（实测 exit 126）；而 Python.framework 的
python3 属于非平台二进制，可以正常访问 Downloads。所以常驻入口一律用 Python，
内部再用 subprocess 调系统命令。

写入 data/timelog/YYYY-MM-DD.tsv，每行 "HH:MM<TAB>AppName"。
键鼠空闲超过 5 分钟记为「离开」。
"""

import os
import subprocess
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGDIR = os.path.join(ROOT, "data", "timelog")
IDLE_LIMIT_SEC = 300

AS_CMD = [
    "osascript", "-e",
    'tell application "System Events" to get name of first application process whose frontmost is true',
]


def frontmost_app():
    """当前前台 App 名；取不到返回空串。"""
    try:
        r = subprocess.run(AS_CMD, capture_output=True, text=True, timeout=10)
        return (r.stdout or "").strip()
    except Exception:
        return ""


def idle_seconds():
    """键鼠空闲秒数；取不到返回 0。"""
    try:
        r = subprocess.run(["ioreg", "-c", "IOHIDSystem"],
                           capture_output=True, text=True, timeout=10)
        for line in r.stdout.splitlines():
            if "HIDIdleTime" in line:
                ns = int(line.rstrip().split("=")[-1].strip())
                return ns // 1_000_000_000
    except Exception:
        pass
    return 0


def main():
    app = frontmost_app()
    if not app:
        return 0            # 未授权 System Events 时静默跳过
    if idle_seconds() > IDLE_LIMIT_SEC:
        app = "离开"

    os.makedirs(LOGDIR, exist_ok=True)
    now = datetime.now()
    path = os.path.join(LOGDIR, now.strftime("%Y-%m-%d") + ".tsv")
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"{now.strftime('%H:%M')}\t{app}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
