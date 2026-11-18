"""看板项目的统一路径与配置解析。

所有渲染脚本都从这里取路径，不再各自硬编码。项目根由本文件位置推导
（render/ 的上一级），因此整个项目目录可以随意移动，无需修改任何脚本。

目录结构：
    <ROOT>/bin/      运行时常驻脚本（serve.py、watchdog.py 等）
    <ROOT>/render/   看板渲染与周报脚本（本文件所在）
    <ROOT>/data/     运行数据（timelog、pages、reports、日志、状态文件）

本机配置：
    把需要覆盖的变量写进 <ROOT>/data/config.env（KEY=VALUE 每行一个），
    或直接用环境变量。参考 data/config.env.example。
    data/ 已被 .gitignore 排除，配置不会进版本库。
"""

import os
import shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")

TIMELOG = os.path.join(DATA, "timelog")
PAGES = os.path.join(DATA, "pages")
REPORTS = os.path.join(DATA, "reports")

CONFIG_FILE = os.path.join(DATA, "config.env")


def load_local_env():
    """把 data/config.env 读进环境变量（不覆盖已存在的同名变量）。"""
    if not os.path.exists(CONFIG_FILE):
        return
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    except OSError:
        pass


load_local_env()


def _first_existing(*paths):
    for p in paths:
        if p and os.path.exists(p):
            return p
    return paths[-1] if paths else ""


# ── 飞书官方 CLI（lark-cli）─────────────────────────────────
# 优先级：环境变量 LARK_CLI > PATH 里的 lark-cli > 常见安装位置
LARK_CLI = _first_existing(
    os.environ.get("LARK_CLI", ""),
    shutil.which("lark-cli") or "",
    os.path.expanduser("~/.npm-global/bin/lark-cli"),
    "/opt/homebrew/bin/lark-cli",
    "/usr/local/bin/lark-cli",
)

# ── Kindle 设备 ────────────────────────────────────────────
# 设备的 WiFi MAC（Amazon Technologies 前缀），用于按 MAC 反查当前 IP。
# 留空则只能手工在 data/.kindle-ip 里写 IP，或依赖 DHCP 固定租约。
KINDLE_MAC = os.environ.get("KINDLE_MAC", "").strip()

# 图床端口（Mac 端 serve.py 监听，Kindle 端 dash.sh 拉图）
DASH_PORT = int(os.environ.get("DASH_PORT", "8077") or 8077)

# ── 可选的共用件 ───────────────────────────────────────────
# 额度页（01-quota）需要 query_deepseek / query_kimi 两个函数。
# 它们放在单独的共用模块里，默认从 QUOTA_MODULE_DIR 指向的目录导入；
# 不配置时额度页会显示 N/A，其余三页不受影响。
QUOTA_MODULE_DIR = os.environ.get("QUOTA_MODULE_DIR", "")

# Proma 工作区：存放 .env（模型 API key），仅额度页用到。
WS = os.environ.get("PROMATEST_WS", "")


def ensure_dirs():
    """创建渲染需要的输出目录。"""
    for d in (TIMELOG, PAGES, REPORTS):
        os.makedirs(d, exist_ok=True)


def error_text(e):
    """把异常翻译成看板上能直接给使用者看的短句。

    不要把原始异常字符串画到屏幕上：JSONDecodeError 的
    "Expecting value: line 1 column 1 (char 0)" 这类内容对用户没有任何意义。
    详细堆栈永远写到 stderr / 日志。
    """
    name, msg = type(e).__name__, str(e)
    low = msg.lower()
    if "no such file" in low or "not found" in low or "找不到" in msg:
        return "未找到 lark-cli，见 README 配置"
    if "permission" in low or "denied" in low:
        return "权限不足"
    if "timed out" in low or "timeout" in low:
        return "数据源超时"
    if "json" in name.lower() or "expecting value" in low:
        return "数据源返回异常"
    if "unable to open database" in low or "sqlite" in low:
        return "本地数据库不可读"
    return "数据源不可用"


def page(name):
    """返回某页的输出路径，例如 page('01-quota.png')。"""
    return os.path.join(PAGES, name)
