#!/usr/bin/env python3
"""用固定假数据渲染四页看板，生成 README 演示图。

为什么这样做：真实渲染图会带上使用者的日程、待办、账户余额等个人内容，
不适合公开。本脚本把各页的数据来源替换成内置的虚构数据，走同一条渲染
链路输出 PNG——版式、字体、灰度层次与真机完全一致，内容干净可公开。

用法：
    python3 scripts/make_demo_assets.py

输出：
    docs/assets/demo/01-quota.png ... 04-timeline.png   单页
    docs/assets/demo/overview.png                       四页拼合图（README 首屏）
"""

import os
import sys
import tempfile
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RENDER = os.path.join(ROOT, "render")
sys.path.insert(0, RENDER)

OUT_DIR = os.path.join(ROOT, "docs", "assets", "demo")

# ── 演示用虚构数据 ────────────────────────────────────────
# 全部为占位内容，不涉及任何真实客户、项目或个人信息。

# 演示用的「现在」：固定在工作时间，让渲染结果稳定、且能展示「进行中」高亮。
DEMO_HOUR, DEMO_MINUTE = 15, 10

DEMO_EVENTS_TODAY = [
    # (开始 HH:MM, 时长[分钟], 标题)
    ("09:30", 60, "设计评审 | Dashboard v2"),
    ("10:30", 45, "周会 · 进度同步"),
    ("11:15", 45, "接口契约对齐"),
    ("12:00", 90, "午休"),
    ("13:30", 110, "深度工作 · 渲染管线"),
    ("15:20", 45, "需求评审 · 移动端"),
    ("16:20", 60, "整理纪要与排期"),
    ("17:20", 40, "收尾与明日计划"),
]

DEMO_EVENTS_TOMORROW = [
    ("10:00", 60, "设计评审 v3"),
    ("14:00", 90, "发布准备"),
]

DEMO_TODOS = [
    # (标题, 截止偏移[天] 或 None, 来源标签)
    ("Dashboard v2 图表组件联调", -9, "P"),
    ("移动端登录流程验收", -6, "P"),
    ("接口文档补全", -2, "飞书"),
    ("撰写 v1.0 发布说明", 0, "飞书"),
    ("导出 App 图标全尺寸", 1, "飞书"),
    ("录制 demo 演示视频", 4, "P"),
    ("部署文档站点", 7, "P"),
    ("整理埋点方案", 10, "飞书"),
    ("更新团队周报模板", 20, "P"),
]

# 时间线：一天的真实工作节奏，含午休与手动补录
DEMO_TIMELINE = [
    # (起始, 结束, 前台 App)
    ("09:00", "09:35", "Figma"),
    ("09:35", "09:52", "飞书"),
    ("09:52", "11:20", "Proma"),
    ("11:20", "11:32", "飞书"),
    ("11:32", "13:18", "离开"),          # 落在 11:30–14:00 窗口，自动归「午休」
    ("13:18", "13:30", "飞书"),
    ("13:30", "15:00", "Proma"),
    ("15:00", "15:45", "腾讯会议"),
    ("15:45", "16:12", "Safari"),
    ("16:12", "17:30", "Proma"),
    ("17:30", "17:48", "飞书"),
    ("17:48", "19:10", "Proma"),
]

DEMO_MANUAL = [
    # (起始, 结束, 补录描述) —— 覆盖自动段，演示「手动补录」能力
    ("09:35", "09:52", "例会 · 进度同步"),
    ("15:00", "15:45", "评审 · 移动端需求"),
]

DEMO_QUOTA = {
    "deepseek_balance": "128.40",
    "kimi_week": 42,
    "kimi_5h": 6,
    "reset_week": "11/20 16:19",
    "reset_5h": "20:19",
}


def write_demo_timelog(day, outdir):
    """按 DEMO_TIMELINE 生成逐分钟的 TSV，格式与 time_logger.py 一致。"""
    os.makedirs(outdir, exist_ok=True)
    lines = []
    for start, end, app in DEMO_TIMELINE:
        sh, sm = (int(x) for x in start.split(":"))
        eh, em = (int(x) for x in end.split(":"))
        cur, stop = sh * 60 + sm, eh * 60 + em
        while cur < stop:
            lines.append(f"{cur // 60:02d}:{cur % 60:02d}\t{app}")
            cur += 1
    with open(os.path.join(outdir, day + ".tsv"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    with open(os.path.join(outdir, day + ".manual.tsv"), "w", encoding="utf-8") as f:
        f.write("\n".join(f"{s}-{e}\t{t}" for s, e, t in DEMO_MANUAL) + "\n")


def demo_schedule_fetch():
    """伪造日程：固定工作时段，配合伪造的「现在」展示进行中高亮。"""
    today = demo_now().date()
    events = []
    for hhmm, dur, title in DEMO_EVENTS_TODAY:
        h, m = (int(x) for x in hhmm.split(":"))
        start = datetime.combine(today, datetime.min.time()).replace(hour=h, minute=m)
        events.append({
            "start": start, "end": start + timedelta(minutes=dur),
            "allday": False, "cal": "工作", "title": title,
        })
    base = datetime.combine(today + timedelta(days=1), datetime.min.time())
    for hhmm, dur, title in DEMO_EVENTS_TOMORROW:
        h, m = (int(x) for x in hhmm.split(":"))
        start = base.replace(hour=h, minute=m)
        events.append({
            "start": start, "end": start + timedelta(minutes=dur),
            "allday": False, "cal": "工作", "title": title,
        })
    return events, None


def demo_now():
    """演示用的固定「现在」：当天 DEMO_HOUR:DEMO_MINUTE。"""
    today = datetime.now().date()
    return datetime.combine(today, datetime.min.time()).replace(
        hour=DEMO_HOUR, minute=DEMO_MINUTE)


def fake_datetime_class():
    """构造一个 now() 恒返回 demo_now() 的 datetime 子类，用于 patch 渲染模块。

    各渲染脚本内部都用模块级的 `datetime.now()` 取时间，替换模块命名空间里的
    这个类即可让整条渲染链看到同一个「现在」——版式里就不会出现 22:12 开会的
    怪时间，页脚时刻也与日程对齐。
    """
    real = datetime

    class FakeDatetime(real):
        @classmethod
        def now(cls, tz=None):
            fixed = demo_now()
            return fixed.astimezone(tz) if tz else fixed

    return FakeDatetime


def demo_todo_fetch():
    """伪造待办：逾期 / 近期 / 远期 三档都有，展示反色置顶与分组。"""
    now = datetime.now()
    items = []
    for title, day_offset, src in DEMO_TODOS:
        due = None if day_offset is None else now + timedelta(days=day_offset)
        items.append({"title": title, "due": due, "src": src})
    return items, None


def demo_quota_fetch():
    balance = float(DEMO_QUOTA["deepseek_balance"])
    kimi = {
        "five_h": DEMO_QUOTA["kimi_5h"],
        "week": DEMO_QUOTA["kimi_week"],
        "reset_5h": DEMO_QUOTA["reset_5h"],
        "reset_week": DEMO_QUOTA["reset_week"],
    }
    return balance, DEMO_QUOTA["deepseek_balance"], kimi


def fake_status_bar(thumb_w, bar_h):
    """模拟 Kindle 原生顶部状态栏：左侧时钟、右侧电池。

    真实设备上顶部 100px 由 Kindle 系统绘制（dash.sh 用 eips -y 100 贴图），
    演示图里补一条，观感才接近真机。
    """
    from PIL import Image, ImageDraw

    bar = Image.new("L", (thumb_w, bar_h), 250)
    d = ImageDraw.Draw(bar)
    from dash_style import load_font
    try:
        f = load_font(max(11, int(bar_h * 0.42)), "regular")
    except Exception:
        f = None
    label = f"{DEMO_HOUR:02d}:{DEMO_MINUTE:02d}"
    x = int(thumb_w * 0.05)
    y = int(bar_h * 0.26)
    if f:
        d.text((x, y - 4), label, font=f, fill=40)
        # 电池：外框 + 正极 + 三格电量
        bw, bh = int(thumb_w * 0.20), int(bar_h * 0.30)
        bx = thumb_w - int(thumb_w * 0.05) - bw
        by = int(bar_h * 0.36)
        d.rectangle([bx, by, bx + bw, by + bh], outline=60, width=1)
        d.rectangle([bx + bw, by + bh // 3, bx + bw + 3, by + bh - bh // 3], fill=60)
        for i in range(3):
            px = bx + 2 + i * (bw - 4) // 3
            d.rectangle([px, by + 2, px + (bw - 4) // 3 - 2, by + bh - 2], fill=60)
    d.line([0, bar_h - 1, thumb_w, bar_h - 1], fill=225)
    return bar


def build_overview(pages, out_path):
    """四页拼成一张横向展示图，浅灰底 + 圆角卡片 + 模拟状态栏。"""
    from PIL import Image, ImageDraw

    thumb_w = 380
    gap, pad = 22, 28
    thumbs = []
    for p in pages:
        im = Image.open(p).convert("L")
        # 内容区 H=1348 是扣掉顶部状态栏后的高度，补回 100px 才是整屏比例
        full_h = int(im.height * 1448 / 1348)
        top_pad = full_h - im.height
        full = Image.new("L", (im.width, full_h), 250)
        full.paste(im, (0, top_pad))
        full.paste(fake_status_bar(im.width, top_pad), (0, 0))
        ratio = thumb_w / full.width
        thumbs.append(full.resize((thumb_w, int(full.height * ratio)), Image.LANCZOS))

    th = max(t.height for t in thumbs)
    canvas_w = pad * 2 + thumb_w * len(thumbs) + gap * (len(thumbs) - 1)
    canvas_h = pad * 2 + th
    canvas = Image.new("L", (canvas_w, canvas_h), 240)

    radius = 10
    mask = Image.new("L", (thumb_w, th), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, thumb_w - 1, th - 1], radius, fill=255)

    for i, t in enumerate(thumbs):
        x = pad + i * (thumb_w + gap)
        canvas.paste(t, (x, pad + (th - t.height) // 2), mask)

    canvas.save(out_path, optimize=True)
    print(f"  overview {canvas_w}x{canvas_h} → {out_path}")


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    day = datetime.now().strftime("%Y-%m-%d")

    # 时间线页读的是 data/timelog/<day>.tsv，这里指到临时目录
    tmpdir = tempfile.mkdtemp(prefix="kindle-demo-")
    write_demo_timelog(day, tmpdir)

    import render_todo
    import render_schedule
    import render_timeline
    import kindle_quota_render

    # 统一「现在」：让四页的时刻逻辑对齐、版式稳定
    FakeDatetime = fake_datetime_class()
    for mod in (render_todo, render_schedule, render_timeline, kindle_quota_render):
        mod.datetime = FakeDatetime

    # 时间线：改模块级 LOGDIR，走真实 load_segments 逻辑
    render_timeline.LOGDIR = tmpdir

    # 待办：替换两个数据源
    render_todo.fetch_lark_tasks = lambda: demo_todo_fetch()
    render_todo.fetch_proma_todos = lambda: ([], None)

    # 日程：替换两个数据源
    render_schedule.fetch_apple = lambda: demo_schedule_fetch()
    render_schedule.fetch_lark = lambda: ([], None)

    # 额度：替换查询函数（模块内是按名字绑定的，必须 patch 到这里）
    balance, balance_str, kimi = demo_quota_fetch()
    kindle_quota_render.query_deepseek = lambda: (balance, balance_str)
    kindle_quota_render.query_kimi = lambda: kimi

    pages = []
    for mod, name in (
        (kindle_quota_render, "01-quota.png"),
        (render_schedule, "02-schedule.png"),
        (render_todo, "03-todo.png"),
        (render_timeline, "04-timeline.png"),
    ):
        out = os.path.join(OUT_DIR, name)
        try:
            mod.render(out)
            pages.append(out)
            print(f"  ok {name}")
        except Exception as e:
            print(f"  fail {name}: {e}", file=sys.stderr)

    if len(pages) == 4:
        build_overview(pages, os.path.join(OUT_DIR, "overview.png"))

    print(f"\n输出目录：{OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
