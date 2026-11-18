#!/usr/bin/env python3
"""按 MAC 地址定位 Kindle 的当前 IP。

背景：Kindle 的 IP 由路由器 DHCP 分配，重连 WiFi / 长时间关机后会变。
写死 IP 的脚本在地址被别的设备接管后，SSH 会打到错误的机器上，
所以这里改为按 MAC 反查当前地址。

用法：
    python3 kindle_ip.py          # 输出 IP，找不到则输出空并以 1 退出
    python3 kindle_ip.py --wake   # 找不到时先做一轮 ping 扫描唤醒，再找
"""
import re
import subprocess
import sys
import os
import concurrent.futures

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "render"))
from dash_paths import KINDLE_MAC  # noqa: E402  在 data/config.env 里设置 KINDLE_MAC
# 本文件在 <ROOT>/bin/ 下，状态文件放 <ROOT>/data/
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DATA = os.path.join(_ROOT, "data")
CACHE = os.path.join(_DATA, ".kindle-ip")
CAND_FILE = os.path.join(_DATA, ".kindle-candidates")
# 路由器 LAN 网段可能变（换路由、改配置都会变），
# 所以不能写死前缀，改为按本机当前在用接口的网段自动推导。
PRIVATE_NETS = ("192.168.", "10.", "172.16.", "172.17.", "172.18.", "172.19.",
                "172.2", "172.30.", "172.31.")

def local_subnets() -> list:
    """返回本机当前所有私有 IPv4 的 /24 前缀（含跨网段可达的旧网段）。"""
    out = subprocess.run(["ifconfig"], capture_output=True, text=True).stdout
    prefixes = []
    for m in re.finditer(r"inet (\d+\.\d+\.\d+)\.\d+", out):
        net = m.group(1) + "."
        if net.startswith("127.") or net.startswith("169.254."):
            continue
        if any(net.startswith(p) for p in PRIVATE_NETS):
            prefixes.append(net)
    return sorted(set(prefixes)) or ["192.168.1."]


def norm(mac: str) -> str:
    """把 arp 输出里省略前导零的 MAC 规范化，如 aa:bb:c:dd:ee:ff → aa:bb:cc:dd:ee:ff"""
    parts = mac.split(":")
    if len(parts) != 6:
        return ""
    return ":".join(p.zfill(2) for p in parts).lower()


def arp_table() -> dict:
    """返回 {ip: 规范化MAC}，覆盖本机所有私有网段。"""
    out = subprocess.run(["arp", "-an"], capture_output=True, text=True).stdout
    prefixes = local_subnets()
    table = {}
    for line in out.splitlines():
        m = re.search(r"\((\d+\.\d+\.\d+\.\d+)\) at ([0-9a-fA-F:]+)", line)
        if not m:
            continue
        ip, mac = m.group(1), norm(m.group(2))
        if mac and any(ip.startswith(p) for p in prefixes):
            table[ip] = mac
    return table


def find() -> str:
    """在 ARP 表里按 MAC 找 IP。"""
    for ip, mac in arp_table().items():
        if mac == KINDLE_MAC:
            return ip
    return ""


def cached() -> str:
    try:
        with open(CACHE) as f:
            ip = f.read().strip()
    except OSError:
        return ""
    if not ip:
        return ""
    # 缓存必须与 MAC 吻合才算数，避免 IP 被别的设备接管后误用
    if arp_table().get(ip) == KINDLE_MAC:
        return ip
    return ""


def save(ip: str) -> None:
    try:
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        with open(CACHE, "w") as f:
            f.write(ip + "\n")
    except OSError:
        pass


def sweep() -> None:
    """快速 ping 扫描，促使 ARP 表刷新（Kindle 深睡时也可能被唤醒）。"""
    prefixes = local_subnets()

    def one(args):
        prefix, i = args
        subprocess.run(
            ["ping", "-c1", "-W", "250", "-t", "1", f"{prefix}{i}"],
            capture_output=True,
        )

    jobs = [(p, i) for p in prefixes for i in range(2, 255)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=64) as pool:
        list(pool.map(one, jobs))


def candidate_prefixes() -> list:
    """历史可达 IP 所在的网段（跨网段场景下 Kindle 不在本机网段里）。"""
    prefixes = set(local_subnets())
    try:
        with open(CAND_FILE) as f:
            for line in f:
                ip = line.strip()
                if ip.count(".") == 3:
                    prefixes.add(ip.rsplit(".", 1)[0] + ".")
    except OSError:
        pass
    return sorted(prefixes)


def probe_ssh_hosts(prefix: str) -> str:
    """扫一个 /24 的 22 端口，用 hostname 确认是 Kindle。

    用于跨网段场景：Kindle 接在 A 网段、Mac 接在 B 网段时，
    两者 ARP 互相看不见，只能靠 TCP 探测（默认扫 22 端口）找回设备。
    """
    key = os.path.expanduser("~/.ssh/id_rsa")

    def one(i):
        ip = f"{prefix}{i}"
        r = subprocess.run(
            ["nc", "-z", "-G", "1", ip, "22"], capture_output=True)
        if r.returncode != 0:
            return None
        # 端口开着不等于就是 Kindle，必须验 hostname
        h = subprocess.run(
            ["ssh", "-o", "ConnectTimeout=3", "-o", "StrictHostKeyChecking=no",
             "-o", "IdentitiesOnly=yes", "-i", key, "-o", "BatchMode=yes",
             f"root@{ip}", "uname -n"], capture_output=True, text=True)
        out = h.stdout.strip().lower()
        return ip if "kindle" in out else None

    with concurrent.futures.ThreadPoolExecutor(max_workers=48) as pool:
        for res in pool.map(one, range(2, 255)):
            if res:
                return res
    return ""


def main() -> int:
    ip = cached() or find()

    # 跨网段兜底：本机网段与历史候选网段都扫一遍 SSH + hostname
    if not ip and ("--wake" in sys.argv or "--cross" in sys.argv):
        for prefix in candidate_prefixes():
            ip = probe_ssh_hosts(prefix)
            if ip:
                break

    if not ip and "--wake" in sys.argv:
        sweep()
        ip = find()

    if not ip:
        print("", end="")
        return 1
    save(ip)
    print(ip)
    return 0


if __name__ == "__main__":
    sys.exit(main())
