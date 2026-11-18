#!/usr/bin/env python3
"""Kindle 看板看门狗：由 launchd 每分钟调用。

职责（与原 shell 版等价）：
  A. 有私有 IP → 保证 8077 图床服务在跑；无网络 → 停掉
  B. Kindle 可达时登记开机自启（/mnt/us/usbnet/auto）
  C. Kindle 端 dash.sh 的 SERVER 地址与 Mac 当前 IP 不一致时自愈
  D. 设备侧健康保底：dash.sh 进程死掉或地址被改坏时自动重启看板

为什么用 Python：项目位于 ~/Downloads 下，macOS TCC 把 /bin/sh、/bin/bash
当作 "Platform Binary" 直接 Deny（实测 exit 126）；Python.framework 的
python3 属非平台二进制，可正常访问 Downloads 并 ssh 到 Kindle。

历史教训（勿回退）：
  - 不要写死网段（路由器换了 LAN 段曾导致看板静默停摆）
  - 不要每分钟 SSH 敲门（会把 Kindle WiFi 从休眠拽起来，白耗电）
"""

import os
import re
import subprocess
import sys
import time
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = os.path.join(ROOT, "data")
BINDIR = os.path.join(ROOT, "bin")
PYTHON = sys.executable

KEY = os.path.expanduser("~/.ssh/id_rsa")
SSH_OPTS = [
    "-o", "StrictHostKeyChecking=no", "-o", "IdentitiesOnly=yes",
    "-i", KEY, "-o", "ConnectTimeout=4", "-o", "BatchMode=yes",
]
KNOWN_KIP_FILE = os.path.join(BASE, ".kindle-candidates")
SERVER_LOG = os.path.join(BASE, "server.log")

KINDLE_DASH_DIR = "/mnt/us/kindle-dash"
RESTART_MIN_ALIVE = 3          # dash.sh 正常会有 6~7 个进程
CROSS_INTERVAL = 600           # 跨网段扫描最快 10 分钟一次
LIVENESS_INTERVAL = 600        # 设备健康检查最快 10 分钟一次


def log(msg):
    line = f"{datetime.now():%m/%d %H:%M} {msg}\n"
    try:
        with open(SERVER_LOG, "a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass


def read_state(name, default=""):
    try:
        with open(os.path.join(BASE, name), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return default


def write_state(name, value):
    try:
        os.makedirs(BASE, exist_ok=True)
        with open(os.path.join(BASE, name), "w", encoding="utf-8") as f:
            f.write(str(value))
    except OSError:
        pass


def age(name):
    """状态文件距今秒数；不存在返回极大值。"""
    try:
        return time.time() - os.path.getmtime(os.path.join(BASE, name))
    except OSError:
        return 1e9


def local_ip():
    for iface in ("en0", "en1"):
        try:
            r = subprocess.run(["ipconfig", "getifaddr", iface],
                               capture_output=True, text=True, timeout=5)
            ip = (r.stdout or "").strip()
            if ip:
                return ip
        except Exception:
            continue
    return ""


def is_private(ip):
    return bool(ip) and not ip.startswith("127.") and not ip.startswith("169.254.")


# ── HTTP 图床服务 ──────────────────────────────
def serve_alive():
    try:
        r = subprocess.run(["pgrep", "-f", "serve.py"], capture_output=True)
        return r.returncode == 0
    except Exception:
        return False


def start_serve():
    try:
        os.makedirs(BASE, exist_ok=True)
        with open(SERVER_LOG, "a", encoding="utf-8") as out:
            subprocess.Popen(
                [PYTHON, os.path.join(BINDIR, "serve.py")],
                cwd=BASE, stdout=out, stderr=out, start_new_session=True)
        log("已启动 serve.py")
    except Exception as e:
        log(f"启动 serve.py 失败: {e}")


def stop_serve():
    try:
        subprocess.run(["pkill", "-f", "serve.py"], capture_output=True)
    except Exception:
        pass


# ── SSH 到 Kindle ──────────────────────────────
def ssh(kip, remote_cmd, timeout=20):
    """执行远程命令；失败返回 None。"""
    cmd = ["ssh"] + SSH_OPTS + [f"root@{kip}", remote_cmd]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout if r.returncode == 0 else None
    except Exception:
        return None


def is_kindle(kip):
    """验证目标确为 Kindle（跨网段时防止认错机器）。"""
    out = ssh(kip, "uname -n", timeout=8)
    return bool(out) and "kindle" in out.lower()


def find_kindle():
    """按 ARP MAC → 候选 IP → 跨网段扫描 → ARP 唤醒扫描，逐级降级。"""
    # 1) 同网段：按 MAC 从 ARP 表定位
    try:
        r = subprocess.run([PYTHON, os.path.join(BINDIR, "kindle_ip.py")],
                           capture_output=True, text=True, timeout=30)
        ip = (r.stdout or "").strip()
        if ip:
            return ip
    except Exception:
        pass

    # 2) 历史候选 IP（跨网段三层互通时 ARP 看不到对方）
    try:
        with open(KNOWN_KIP_FILE, encoding="utf-8") as f:
            for cand in f.read().split():
                if cand and is_kindle(cand):
                    return cand
    except OSError:
        pass

    # 3) 跨网段 TCP 扫描 + hostname 验证（慢，限频）
    if age(".last-cross") >= CROSS_INTERVAL:
        write_state(".last-cross", int(time.time()))
        try:
            r = subprocess.run([PYTHON, os.path.join(BINDIR, "kindle_ip.py"), "--cross"],
                               capture_output=True, text=True, timeout=120)
            ip = (r.stdout or "").strip()
            if ip:
                log(f"跨网段扫描找回 Kindle：{ip}")
                return ip
        except Exception:
            pass

    # 4) ping 扫描刷新 ARP（Kindle 深睡后 ARP 里没有它）
    if age(".last-sweep") >= CROSS_INTERVAL:
        write_state(".last-sweep", int(time.time()))
        try:
            r = subprocess.run([PYTHON, os.path.join(BINDIR, "kindle_ip.py"), "--wake"],
                               capture_output=True, text=True, timeout=180)
            ip = (r.stdout or "").strip()
            if ip:
                return ip
        except Exception:
            pass

    return ""


def set_server_ip(kip, myip):
    """把 Kindle 端 dash.sh 的 SERVER 指向当前 Mac IP。"""
    return ssh(kip, f"sed -i 's|http://[0-9.]*:8077|http://{myip}:8077|' "
                    f"{KINDLE_DASH_DIR}/dash.sh")


def restart_dash(kip):
    return ssh(kip, f"sh {KINDLE_DASH_DIR}/launch.sh")


# ── 主流程 ────────────────────────────────────
def main():
    myip = local_ip()
    if not is_private(myip):
        stop_serve()
        return 0

    # A. 图床服务
    if not serve_alive():
        start_serve()

    kip = find_kindle()
    if not kip:
        return 0                    # 设备离线/深睡：静默退出

    # B. 登记开机自启（只需成功一次）
    if not os.path.exists(os.path.join(BASE, ".auto-ensured")):
        if ssh(kip, "mkdir -p /mnt/us/usbnet && touch /mnt/us/usbnet/auto") is not None:
            write_state(".auto-ensured", "")
            log(f"已登记 Kindle 开机自启 SSH（{kip}）")

    # D. 设备侧健康保底：进程存活 + SERVER 地址（独立于 IP 变化判断）
    hour = datetime.now().hour
    if age(".last-liveness") >= LIVENESS_INTERVAL and 9 <= hour < 21:
        probe = ssh(kip,
                    'echo "ALIVE=$(pgrep -f /tmp/dash.sh | wc -l)"; '
                    f'sed -n \'s|SERVER="http://\\([^:]*\\):.*|SRV=\\1|p\' {KINDLE_DASH_DIR}/dash.sh')
        # 探测成功才记账：否则瞬时 SSH 失败要白等 10 分钟才重试
        if probe:
            write_state(".last-liveness", int(time.time()))
            m_alive = re.search(r"ALIVE=(\d+)", probe)
            m_srv = re.search(r"SRV=([0-9.]+)", probe)
            alive = int(m_alive.group(1)) if m_alive else None
            srv = m_srv.group(1) if m_srv else ""

            reasons = []
            if alive is not None and alive < RESTART_MIN_ALIVE:
                reasons.append(f"看板进程缺失（{alive}）")
            if srv and srv != myip:
                set_server_ip(kip, myip)
                reasons.append(f"SERVER {srv}→{myip}")
            if reasons:
                restart_dash(kip)
                log("看板已重启：" + "；".join(reasons))

    # C. 状态变化时立即自愈（IP 变了马上连一次，不等 10 分钟节拍）
    if read_state(".last-kip") != kip or read_state(".last-myip") != myip:
        set_server_ip(kip, myip)
        restart_dash(kip)
        log(f"IP 变化自愈：Kindle={kip} Mac={myip}")

    write_state(".last-kip", kip)
    write_state(".last-myip", myip)

    # 记住可达 IP，供跨网段复用
    try:
        known = []
        if os.path.exists(KNOWN_KIP_FILE):
            with open(KNOWN_KIP_FILE, encoding="utf-8") as f:
                known = f.read().split()
        if kip not in known:
            with open(KNOWN_KIP_FILE, "a", encoding="utf-8") as f:
                f.write(kip + "\n")
    except OSError:
        pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
