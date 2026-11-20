#!/usr/bin/env python3
"""macOS 菜单栏状态指示：一眼看出 Kindle 看板是否在正常工作。

菜单栏文字形如 `📟🟢3m`：
    🟢  一切正常     后面的数字 = Kindle 上次拉图距今几分钟
    🟡  有异常       端口在、但 Kindle 太久没拉图 / 渲染停了 / 某页渲染失败
    🔴  图床没起来    :8077 无人监听，Kindle 拉不到图
    🌙  夜间休眠     21:00–09:00 Kindle 按设计放睡，不拉图属正常

点开有详情：图床状态与 PID、Kindle 当前 IP 与拉图时间、四页渲染新鲜度、
Mac 当前 IP；并可直接打开预览页 / 手动渲染 / 重启图床 / 看日志。

依赖 PyObjC（pip install pyobjc-framework-Cocoa），install.sh 会自动装。
为什么用 Python：本项目位于 ~/Downloads 下，macOS TCC 会把 /bin/sh、/bin/bash
当作 "Platform Binary" 直接 Deny；Python.framework 的 python3 不受此限。

状态判定全部来自现有产物（不额外打扰设备，避免把 Kindle 的 WiFi 从休眠拽起来）：
  - 图床：TCP 连 127.0.0.1:8077（只连端口，不请求 /quota.png，否则会推进轮播）
  - Kindle：data/server.log 里最后一条 "<ip> <- <page>" 的时间
  - 渲染：data/pages/*.png 的最新 mtime + /tmp/kindle-render.log 的失败行
"""

import glob
import os
import re
import socket
import subprocess
import sys
import time
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = os.path.join(ROOT, "data")
PAGES_DIR = os.path.join(BASE, "pages")
SERVER_LOG = os.path.join(BASE, "server.log")
RENDER_LOG = "/tmp/kindle-render.log"
PID_FILE = os.path.join(BASE, ".menubar.pid")

sys.path.insert(0, os.path.join(ROOT, "render"))
try:
    from dash_paths import DASH_PORT
except Exception:                                   # 极端情况下也能跑
    DASH_PORT = int(os.environ.get("DASH_PORT", "8077") or 8077)

REFRESH_SEC = 30          # 菜单栏刷新节拍
PULL_OK_MIN = 12          # Kindle 每 5 分钟拉一次，12 分钟内有动作算在线
PULL_WARN_MIN = 25        # 超过这个还没拉 → 视为掉线
RENDER_OK_MIN = 20        # 渲染调度每 5 分钟，20 分钟内更新过算正常
NIGHT_START, NIGHT_END = 21, 9     # 与设备端 dash.sh 的放睡时段一致

PAGE_ORDER = ["01-quota.png", "02-schedule.png", "03-todo.png", "04-timeline.png"]
PAGE_LABEL = {
    "01-quota.png": "额度",
    "02-schedule.png": "日程",
    "03-todo.png": "待办",
    "04-timeline.png": "时间线",
}

# ── 状态采集（纯本地，无副作用）──────────────────────────


def port_open(port, timeout=0.8):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout):
            return True
    except OSError:
        return False


def server_pid():
    """图床进程 PID（launchd 里也可能显示为 -，所以直接 pgrep）。"""
    try:
        r = subprocess.run(["pgrep", "-f", os.path.join(ROOT, "bin", "serve.py")],
                           capture_output=True, text=True, timeout=3)
        pids = [p for p in (r.stdout or "").split() if p.strip()]
        return pids[0] if pids else ""
    except Exception:
        return ""


PULL_RE = re.compile(r"^(\d{2})/(\d{2}) (\d{2}):(\d{2}):(\d{2}) (\d+\.\d+\.\d+\.\d+) <-", re.M)


def last_pull(myip=""):
    """返回 (ip, 距今分钟) 或 (None, None)。

    回环和本机 IP 的请求来自 install.sh 的健康检查与浏览器预览，
    不能当成「Kindle 拉过图」，否则会误报在线。
    """
    try:
        size = os.path.getsize(SERVER_LOG)
        with open(SERVER_LOG, "rb") as f:
            f.seek(max(0, size - 16384))
            text = f.read().decode("utf-8", "replace")
    except OSError:
        return None, None
    hits = PULL_RE.findall(text)
    now = datetime.now()
    for mo, dy, hh, mi, ss, ip in reversed(hits):
        if ip.startswith("127.") or (myip and ip == myip):
            continue
        try:
            dt = datetime(now.year, int(mo), int(dy), int(hh), int(mi), int(ss))
        except ValueError:
            return ip, None
        if dt > now:
            dt = dt.replace(year=now.year - 1)      # 跨年时的旧记录
        return ip, (now - dt).total_seconds() / 60
    return None, None


def page_state():
    """返回 [(name, mtime or None)]，按固定顺序。"""
    out = []
    for name in PAGE_ORDER:
        p = os.path.join(PAGES_DIR, name)
        try:
            out.append((name, os.path.getmtime(p)))
        except OSError:
            out.append((name, None))
    return out


def newest_mtime(pages):
    ts = [t for _, t in pages if t]
    return max(ts) if ts else None


RENDER_LINE_RE = re.compile(
    r"^(\d\d/\d\d \d\d:\d\d:\d\d) (ok|fail|error) (\S+?\.png):? ?(.*)$")


def render_results():
    """每页最后一次渲染结果：{page: ("ok"|"fail"|"error", 详情)}。"""
    try:
        size = os.path.getsize(RENDER_LOG)
        with open(RENDER_LOG, "rb") as f:
            f.seek(max(0, size - 32768))
            lines = f.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return {}
    last = {}
    for line in lines:
        m = RENDER_LINE_RE.match(line.strip())
        if m:
            last[m.group(3)] = (m.group(2), m.group(4).strip())
    return last


def local_ip():
    for iface in ("en0", "en1"):
        try:
            r = subprocess.run(["ipconfig", "getifaddr", iface],
                               capture_output=True, text=True, timeout=3)
            ip = (r.stdout or "").strip()
            if ip:
                return ip
        except Exception:
            continue
    return ""


def is_night(now=None):
    h = (now or datetime.now()).hour
    return h >= NIGHT_START or h < NIGHT_END


def derive_state(up, render_ok, pull_age, night):
    """四态判定（纯函数，方便单测）：

    🔴 down  图床没监听 —— Kindle 一定拉不到图，看板是停的
    🟡 warn  图床在但渲染停了/有页面渲染失败/Kindle 白天没拉图
    🟢 ok    图床 + 渲染 + Kindle 拉图都在正常节拍上
    🌙 sleep 夜间放睡（dash.sh 21:00–09:00 不拉图是设计要求）
    """
    if not up:
        return "down"
    if not render_ok:
        return "warn"
    if pull_age is not None and pull_age <= PULL_OK_MIN:
        return "ok"
    if night:
        return "sleep"
    return "warn"


def collect():
    now = time.time()
    up = port_open(DASH_PORT)
    pid = server_pid() if up else ""
    myip = local_ip()
    kip, pull_age = last_pull(myip)
    pages = page_state()
    newest = newest_mtime(pages)
    render_age = (now - newest) / 60 if newest else None
    results = render_results()
    failed = {p: r[1] for p, r in results.items() if r[0] != "ok"}

    render_ok = render_age is not None and render_age <= RENDER_OK_MIN and not failed
    state = derive_state(up, render_ok, pull_age, is_night())

    return {
        "state": state, "up": up, "pid": pid,
        "kip": kip, "pull_age": pull_age,
        "pages": pages, "render_age": render_age, "failed": failed,
        "myip": myip,
    }


DOT = {"ok": "🟢", "warn": "🟡", "down": "🔴", "sleep": "🌙"}
VERDICT = {
    "ok": "正常",
    "warn": "有异常",
    "down": "图床未运行",
    "sleep": "夜间休眠",
}


def title_text(st):
    """菜单栏文字：图标 + 状态点 + 上次拉图距今分钟。"""
    state = st["state"]
    dot = DOT[state]
    age = st["pull_age"]
    if state in ("down", "sleep"):          # 夜间不显示大数字，避免图标变宽
        return f"📟{dot}"
    if age is None:
        return f"📟{dot}—"
    if age < 1:
        return f"📟{dot}"
    if age < 60:
        return f"📟{dot}{int(age)}m"
    return f"📟{dot}{int(age // 60)}h"


def fmt_age(minutes):
    if minutes is None:
        return "无记录"
    if minutes < 1:
        return "刚刚"
    if minutes < 60:
        return f"{int(minutes)} 分钟前"
    hours = minutes / 60
    if hours < 24:
        return f"{hours:.1f} 小时前"
    return f"{hours / 24:.1f} 天前"


def detail_lines(st):
    """菜单里的只读信息行。"""
    rows = []
    if st["up"]:
        pid = f" · PID {st['pid']}" if st["pid"] else ""
        rows.append(f"图床 :{DASH_PORT}　✅ 运行中{pid}")
    else:
        rows.append(f"图床 :{DASH_PORT}　❌ 未监听")

    if st["kip"]:
        line = f"Kindle　{st['kip']} · {fmt_age(st['pull_age'])}拉图"
        if st["state"] == "sleep":
            line += "（夜间放睡）"
        rows.append(line)
    else:
        rows.append("Kindle　暂无拉图记录")

    if st["render_age"] is None:
        rows.append("渲染　❌ 还没有生成任何页面")
    else:
        rows.append(f"渲染　{fmt_age(st['render_age'])}更新")

    if st["failed"]:
        for page, msg in list(st["failed"].items())[:3]:
            label = PAGE_LABEL.get(page, page.replace(".png", ""))
            short = re.sub(r"^\s*rc=\d+:?\s*", "", msg)
            short = re.sub(r"^\s*Error:?\s*", "", short)[:60]
            rows.append(f"⚠️ {label}页：{short}")

    rows.append(f"Mac　{st['myip'] or '无局域网 IP'}")
    return rows


def page_lines(st):
    rows = []
    for name, ts in st["pages"]:
        age = (time.time() - ts) / 60 if ts else None
        mark = "·" if ts and age is not None and age <= 60 else "!"
        label = PAGE_LABEL.get(name, name)
        rows.append(f"　{mark} {label}　{fmt_age(age)}")
    return rows


# ── GUI ──────────────────────────────────────────────────
def main():
    try:
        import objc
        import AppKit
        from AppKit import (
            NSApplication, NSApplicationActivationPolicyAccessory, NSMenu,
            NSMenuItem, NSStatusBar, NSVariableStatusItemLength, NSWorkspace,
        )
        from Foundation import NSURL, NSObject, NSTimer
    except ImportError:
        print("缺少 PyObjC：pip install pyobjc-framework-Cocoa", file=sys.stderr)
        return 2

    # 单实例：launchd 重载或手动重跑时不出现两个图标
    try:
        os.makedirs(BASE, exist_ok=True)
        if os.path.exists(PID_FILE):
            with open(PID_FILE) as f:
                old = f.read().strip()
            if old.isdigit() and int(old) != os.getpid():
                try:
                    os.kill(int(old), 0)
                    print(f"已有实例在运行（PID {old}），退出", file=sys.stderr)
                    return 0
                except OSError:
                    pass
        with open(PID_FILE, "w") as f:
            f.write(str(os.getpid()))
    except OSError:
        pass

    class MenubarApp(NSObject):
        def applicationDidFinishLaunching_(self, _note):
            self.state = None
            self.menu_open = False
            self._last_title = None
            self.status_item = NSStatusBar.systemStatusBar() \
                .statusItemWithLength_(NSVariableStatusItemLength)
            self.status_item.retain()
            button = self.status_item.button()
            if button is not None:
                try:
                    button.setFont_(button.font().fontWithSize_(13))
                except Exception:
                    pass
                # 菜单**平时不挂在 item 上**，只在点击那一刻临时挂上。
                # 如果常驻 setMenu_，系统靠状态项窗口 frame 的缓存算菜单位置；
                # 而这里每 30 秒会重设按钮标题，cache 一旦失效，菜单就会被
                # 丢到屏幕最右侧而不是图标下方（本机实测确实如此）。
                button.setTarget_(self)
                button.setAction_("handleClick:")
                # 这两个掩码只能从 AppKit 模块属性取，from-import 拿不到
                button.sendActionOn_(
                    int(AppKit.NSEventMaskLeftMouseUp) | int(AppKit.NSEventMaskRightMouseUp))
            self.refresh()
            NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                float(REFRESH_SEC), self, "tick:", None, True)
            # 排障用：MENUBAR_SELFTEST=1 时自动弹出菜单，方便核对菜单内容
            if os.environ.get("MENUBAR_SELFTEST") == "1":
                NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                    2.0, self, "selftest:", None, False)

        def selftest_(self, _timer):
            self.handleClick_(self.status_item.button())

        # ── 点击弹菜单 ────────────────────────
        def handleClick_(self, sender):
            """现刷状态 → 临时挂菜单 → performClick 弹 → 摘掉。

            performClick 会阻塞到菜单关闭，所以摘下时菜单已经收起，
            下一次点击系统会按当时真实的按钮位置重新算坐标。
            """
            print("click -> 弹菜单", file=sys.stderr, flush=True)
            self.refresh()
            self.menu_open = True
            try:
                self.status_item.setMenu_(self.build_menu(self.state))
                sender.highlight_(True)
                sender.performClick_(None)
            finally:
                self.status_item.setMenu_(None)
                self.menu_open = False
                sender.highlight_(False)

        # ── 刷新与菜单构建 ─────────────────────
        def tick_(self, _timer):
            self.refresh()

        def refresh(self):
            try:
                st = collect()
            except Exception as e:                   # 绝不让采集异常杀掉图标
                st = {"state": "warn", "up": False, "pid": "", "kip": None,
                      "pull_age": None, "pages": [], "render_age": None,
                      "failed": {"collect": str(e)}, "myip": ""}
            self.state = st
            if self.menu_open:                       # 菜单开着时不改文案，否则会跟着漂
                return
            item = self.status_item
            title = title_text(st)
            # 只在真的变化时才写：反复 setTitle 会引起重新布局，
            # 状态项窗口 frame 的缓存会被打穿，菜单位置又跑掉。
            if title != self._last_title:
                item.button().setTitle_(title)
                self._last_title = title
            item.button().setToolTip_(
                f"Kindle 看板 · {VERDICT[st['state']]}　"
                f"{'拉图 ' + fmt_age(st['pull_age']) if st['pull_age'] is not None else '无拉图记录'}")

        def build_menu(self, st):
            menu = NSMenu.alloc().init()
            menu.setAutoenablesItems_(False)

            head = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                f"Kindle 看板 · {VERDICT[st['state']]}", None, "")
            head.setEnabled_(False)
            menu.addItem_(head)

            menu.addItem_(NSMenuItem.separatorItem())
            for line in detail_lines(st) + page_lines(st):
                it = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(line, None, "")
                it.setEnabled_(False)        # 纯信息行，不做动作
                menu.addItem_(it)

            menu.addItem_(NSMenuItem.separatorItem())
            for title, sel in (
                ("打开预览页", "actPreview:"),
                ("立即重新渲染", "actRender:"),
                ("重启图床服务", "actRestart:"),
                ("打开项目目录", "actFolder:"),
                ("打开日志", "actLog:"),
            ):
                it = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, sel, "")
                it.setTarget_(self)
                menu.addItem_(it)

            menu.addItem_(NSMenuItem.separatorItem())
            it = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("立即刷新", "actRefresh:", "")
            it.setTarget_(self)
            menu.addItem_(it)
            it = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("退出菜单栏图标", "actQuit:", "q")
            it.setTarget_(self)
            menu.addItem_(it)
            return menu

        # ── 菜单动作 ─────────────────────────
        def actPreview_(self, _sender):
            NSWorkspace.sharedWorkspace().openURL_(
                NSURL.URLWithString_(f"http://127.0.0.1:{DASH_PORT}/"))

        def actRender_(self, _sender):
            subprocess.Popen([sys.executable, os.path.join(ROOT, "bin", "render_all.py")],
                             cwd=ROOT, start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.refresh()

        def actRestart_(self, _sender):
            subprocess.Popen(
                ["launchctl", "kickstart", "-k",
                 f"gui/{os.getuid()}/com.proma.kindle-dash-server"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                3.0, self, "tick:", None, False)

        def actFolder_(self, _sender):
            NSWorkspace.sharedWorkspace().openURL_(
                NSURL.fileURLWithPath_(ROOT))

        def actLog_(self, _sender):
            for path in (SERVER_LOG, RENDER_LOG):
                if os.path.exists(path):
                    NSWorkspace.sharedWorkspace().openURL_(
                        NSURL.fileURLWithPath_(path))
                    break

        def actRefresh_(self, _sender):
            self.refresh()

        def actQuit_(self, _sender):
            try:
                os.unlink(PID_FILE)
            except OSError:
                pass
            NSApplication.sharedApplication().terminate_(None)

    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)   # 不占 Dock
    delegate = MenubarApp.alloc().init()
    app.setDelegate_(delegate)
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
