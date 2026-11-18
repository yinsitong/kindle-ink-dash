#!/usr/bin/env python3
"""周时间汇总 + 行为分析报告。

聚合本周（周一~周日）timelog 数据，输出：
1. Markdown 留档：data/reports/weekly-YYYY-MM-DD.md（日期=周五）
2. --push 时把摘要推到飞书群（群 ID 由 LARK_CHAT_ID 指定）

用法：
  python3 weekly_report.py              # 只生成留档
  python3 weekly_report.py --push       # 留档 + 飞书推送
  python3 weekly_report.py --week -1    # 上周
"""

import argparse
import glob
import os
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timedelta

from dash_paths import TIMELOG, REPORTS, PAGES, LARK_CLI  # noqa: E402
LOGDIR = TIMELOG
REPORT_DIR = REPORTS

# 推送目标：留空则 --push 只打印不发送。用 `lark-cli im +chats-list` 查群 ID。
CHAT_ID = os.environ.get("LARK_CHAT_ID", "")

CATEGORIES = {
    "深度工作": ["proma", "word", "excel", "powerpoint", "pages", "numbers", "keynote",
               "figma", "sketch", "pencil", "幕布", "mindnote", "xmind", "notion", "obsidian", "typora",
               "cursor", "code", "trae", "terminal", "iterm", "xcode"],
    "沟通协作": ["lark", "feishu", "飞书", "dingtalk", "钉钉", "企业微信", "wecom", "mail", "邮件"],
    "会议": ["zoom", "teams", "腾讯会议", "voov", "facetime"],
    "浏览": ["safari", "chrome", "arc", "edge", "firefox", "brave"],
    "划水": ["wechat", "微信", "qq", "bilibili", "哔哩", "douyin", "抖音", "weibo", "微博", "xiaohongshu", "小红书"],
}
FRAG_MIN = 15  # <15min 算碎段
WEEKDAYS = "一二三四五六日"


def categorize(app):
    a = app.lower()
    if a == "pen" or "pencil" in a:  # Pen.app / Pencil（原型工具，防 "pen" 误匹配 openai）
        return "深度工作"
    if any(k in a for k in ["finder", "preview", "预览", "updf", "word", "excel", "powerpoint", "wps", "pages", "numbers", "keynote"]):
        return "浏览"  # 打开 Office/PDF/访达 = 看本地文件、客户文档
    for cat, keys in CATEGORIES.items():
        if any(k in a for k in keys):
            return cat
    return "其他"


def hhmm(s):
    hh, mm = s.split(":")
    return int(hh) * 60 + int(mm)


def fmt(mins):
    if mins < 60:
        return f"{mins}m"
    return f"{mins // 60}h{mins % 60:02d}m"


def pct(part, whole):
    return f"{part / whole * 100:.0f}%" if whole else "0%"



def categorize_manual(text):
    """手动补录按内容归类，识别不了才归「补录」"""
    t = text.lower()
    if any(k in t for k in ["开会", "会议", "例会", "评审", "meeting", "语音", "汇报", "面试", "分享"]):
        return "会议"
    if any(k in t for k in ["对接", "供应商", "客户", "合作方", "沟通", "同步"]):
        return "沟通协作"
    if "下班" in t:
        return "下班"
    if any(k in t for k in ["饭", "午休", "吃", "咖啡", "遛弯", "休息", "通勤"]):
        return "离开"
    if any(k in t for k in ["prd", "原型", "文档", "方案", "需求", "设计稿", "写", "整理"]):
        return "深度工作"
    if any(k in t for k in ["微信", "划水", "摸鱼", "刷"]):
        return "划水"
    return "补录"



# 午间窗口内的「离开」自动归为午休；窗口外仍算离开
def cat_with_nap(app, cat, minute):
    if cat == "离开":
        if minute < 7 * 60 or minute >= 23 * 60:
            return "夜间"  # 深夜/凌晨的空闲不算离席
        if 11 * 60 + 30 <= minute < 14 * 60:
            return "午休"
    return cat

def load_day(date_str):
    """返回 minutes: {minute: (app, cat, is_manual)}"""
    minute_map = {}
    auto_path = os.path.join(LOGDIR, date_str + ".tsv")
    if os.path.exists(auto_path):
        for line in open(auto_path, encoding="utf-8", errors="ignore"):
            parts = line.rstrip("\n").split("\t")
            if len(parts) != 2:
                continue
            try:
                m = hhmm(parts[0])
            except ValueError:
                continue
            app = parts[1]
            cat = "离开" if app == "离开" else categorize(app)
            minute_map[m] = (app, cat_with_nap(app, cat, m), False)
    manual_path = os.path.join(LOGDIR, date_str + ".manual.tsv")
    if os.path.exists(manual_path):
        for line in open(manual_path, encoding="utf-8", errors="ignore"):
            parts = line.rstrip("\n").split("\t")
            if len(parts) != 2 or "-" not in parts[0]:
                continue
            try:
                s, e = parts[0].split("-")
                s, e = hhmm(s), hhmm(e)
            except ValueError:
                continue
            for m in range(s, e):
                minute_map[m] = (parts[1].strip(), categorize_manual(parts[1].strip()), True)
    return minute_map


def merge_segments(minute_map):
    segs = []
    for m in sorted(minute_map):
        app, cat, mf = minute_map[m]
        if segs and segs[-1][1] == m and segs[-1][2] == app:
            segs[-1][1] = m + 1
        else:
            segs.append([m, m + 1, app, cat, mf])
    return segs


def analyze_week(days_data):
    """days_data: {date_str: minute_map}"""
    week_cat = defaultdict(int)
    week_app = defaultdict(int)
    all_segs = []
    day_rows = []

    for date_str in sorted(days_data):
        mm = days_data[date_str]
        if not mm:
            continue
        segs = merge_segments(mm)
        all_segs.extend((date_str, s, e, app, cat, mf) for s, e, app, cat, mf in segs)
        cat_min = defaultdict(int)
        app_min = defaultdict(int)
        manual_m = 0
        for s, e, app, cat, mf in segs:
            if app in ("离开", "下班"):
                # 伪条目不计入应用排行（只进分类统计）；夜间/长离开/下班都不算真实应用
                if cat in ("夜间", "下班"):
                    continue
                if cat == "离开" and e - s >= 45:
                    continue  # 长离开（>=45 分钟）= 不在电脑前，不计入
                cat_min[cat] += e - s
                week_cat[cat] += e - s
                continue
            cat_min[cat] += e - s
            week_cat[cat] += e - s
            if not mf:  # 手动补录的是「活动」不是「应用」，不参与 Top 应用排行
                app_min[app] += e - s
                week_app[app] += e - s
            if mf:
                manual_m += e - s
                globals()['__week_manual__'] = globals().get('__week_manual__', 0) + (e - s)
        total = sum(cat_min.values())
        frag = sum(1 for s, e, *_ in segs if e - s < FRAG_MIN)
        switches = sum(1 for i in range(1, len(segs)) if segs[i][2] != segs[i - 1][2])
        focus = 0
        for s, e, app, cat, mf in segs:
            # 会议不算「专注块」：开会是被动在场，不是独立产出的连续工作
            if cat in ("深度工作", "沟通协作"):
                focus = max(focus, e - s)
        act = [(s, e) for s, e, a, c, mf in segs
               if c not in ("夜间", "下班") and not (c == "离开" and e - s >= 45)]
        if act:
            st = min(s for s, e in act)
            en = max(e - 1 for s, e in act)
        else:
            st = en = 0
        day_rows.append({
            "date": date_str,
            "wd": WEEKDAYS[datetime.strptime(date_str, "%Y-%m-%d").weekday()],
            "start": f"{st // 60:02d}:{st % 60:02d}",
            "end": f"{en // 60:02d}:{en % 60:02d}",
            "total": total,
            "cat": dict(cat_min),
            "frag": frag,
            "n_segs": len(segs),
            "switches": switches,
            "focus": focus,
            "manual": manual_m,
        })

    return week_cat, week_app, all_segs, day_rows


def build_insights(week_cat, day_rows, all_segs):
    insights = []
    total = sum(week_cat.values())
    if not total or not day_rows:
        return ["数据不足，下周继续积累。"]

    # 深度工作占比（PM 的产出时间：PRD/原型/文档）
    deep = week_cat.get("深度工作", 0)
    if deep / total < 0.30:
        insights.append(f"⚠️ 深度工作（PRD/原型/文档）占比 {pct(deep, total)}（{fmt(deep)}），作为产品经理产出时间偏少，看看是被什么吃掉了。")
    else:
        insights.append(f"💪 深度工作占比 {pct(deep, total)}（{fmt(deep)}），产出节奏在线。")

    # 划水
    slack = week_cat.get("划水", 0)
    if slack / total > 0.15:
        insights.append(f"🐟 划水（微信等）占比 {pct(slack, total)}（{fmt(slack)}），有点多了——主要是哪个时段在划？")

    # 沟通协作负载
    comm = week_cat.get("沟通协作", 0) + week_cat.get("会议", 0)
    if comm / total > 0.30:
        insights.append(f"⚠️ 正经沟通（飞书+会议）占比 {pct(comm, total)}（{fmt(comm)}）偏高，PM 的日常——但可以试试给上午设「免打扰块」护住产出时间。")

    # 碎片化
    frag_days = sorted(day_rows, key=lambda r: -(r["frag"] / max(r["n_segs"], 1)))
    worst = frag_days[0]
    if worst["n_segs"] and worst["frag"] / worst["n_segs"] > 0.6:
        insights.append(f"🧩 周{worst['wd']}最碎：{worst['frag']}/{worst['n_segs']} 段是 <{FRAG_MIN} 分钟的碎段，切换 {worst['switches']} 次。")

    # 最长专注
    best = max(day_rows, key=lambda r: r["focus"])
    if best["focus"] >= 60:
        insights.append(f"💪 周{best['wd']}有本周最长专注块 {fmt(best['focus'])}，值得复盘当时的状态。")

    # 离开
    idle = week_cat.get("离开", 0)
    if idle / total > 0.45:
        insights.append(f"🚶 离开（键鼠空闲）占比 {pct(idle, total)}（{fmt(idle)}）——线下会议多的话记得用「记一笔」补录。")

    # 手动补录
    manual = globals().get("__week_manual__", 0)
    if manual:
        insights.append(f"✍️ 手动补录 {fmt(manual)}（{pct(manual, total)}），补录让画像更完整，继续保持。")
    return insights


def render_markdown(week_label, week_cat, week_app, day_rows, insights, total):
    L = []
    L.append(f"# 周时间报告 · {week_label}")
    L.append("")
    L.append(f"> 生成于 {datetime.now().strftime('%Y-%m-%d %H:%M')} · 数据源：Mac 前台应用采集 + 手动补录")
    L.append("")
    L.append("## 总览")
    L.append("")
    L.append(f"- 本周记录总时长：**{fmt(total)}**（{len(day_rows)} 天）")
    L.append(f"- 日均：{fmt(total // max(len(day_rows), 1))}")
    L.append("")
    L.append("## 分类占比")
    L.append("")
    L.append("| 分类 | 时长 | 占比 |")
    L.append("| --- | --- | --- |")
    for cat, mins in sorted(week_cat.items(), key=lambda kv: -kv[1]):
        label = cat
        bar = "█" * max(int(mins / max(sum(week_cat.values()), 1) * 20), 1)
        L.append(f"| {label} | {fmt(mins)} | {pct(mins, total)} {bar} |")
    L.append("")
    L.append("## 每日一览")
    L.append("")
    L.append("| 日 | 时段 | 总时长 | 深度工作 | 飞书+会议 | 划水 | 离开 | 最长专注 |")
    L.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for r in day_rows:
        comm = r["cat"].get("沟通协作", 0) + r["cat"].get("会议", 0)
        L.append(
            f"| 周{r['wd']} | {r['start']}–{r['end']} | {fmt(r['total'])} "
            f"| {fmt(r['cat'].get('深度工作', 0))} | {fmt(comm)} | {fmt(r['cat'].get('划水', 0))} "
            f"| {fmt(r['cat'].get('离开', 0))} | {fmt(r['focus'])} |"
        )
    L.append("")
    L.append("## Top 应用")
    L.append("")
    L.append("| 应用 | 时长 | 占比 |")
    L.append("| --- | --- | --- |")
    for app, mins in sorted(week_app.items(), key=lambda kv: -kv[1])[:8]:
        L.append(f"| {app} | {fmt(mins)} | {pct(mins, total)} |")
    L.append("")
    L.append("## 行为洞察")
    L.append("")
    for ins in insights:
        L.append(f"- {ins}")
    L.append("")
    return "\n".join(L)


def render_summary(week_label, week_cat, day_rows, insights, total):
    """飞书摘要（精简版）"""
    top = sorted(week_cat.items(), key=lambda kv: -kv[1])[:5]
    lines = [f"📊 周时间报告 · {week_label}", ""]
    lines.append(f"总时长 {fmt(total)} · {len(day_rows)} 天 · 日均 {fmt(total // max(len(day_rows), 1))}")
    lines.append("")
    for cat, mins in top:
        label = cat
        lines.append(f"▸ {label} {fmt(mins)}（{pct(mins, total)}）")
    lines.append("")
    lines.append("洞察：")
    for ins in insights[:4]:
        lines.append(f"· {ins}")
    return "\n".join(lines)


def push_lark(text):
    r = subprocess.run(
        [LARK_CLI, "im", "+messages-send", "--chat-id", CHAT_ID,
         "--text", text],
        capture_output=True, text=True, timeout=60,
        env={**os.environ,
              "PATH": os.environ.get("PATH", "") + ":" + os.path.expanduser("~/.bun/bin")},
    )
    if r.returncode != 0:
        print(f"⚠ 飞书推送失败: {r.stderr[:200]}", file=sys.stderr)
        return False
    print("✅ 飞书摘要已推送")
    return True


def push_lark_image(img_path):
    """推送周报大图到飞书群（lark-cli --image 需要 cwd-relative 路径）。"""
    cwd = os.path.dirname(os.path.abspath(img_path))
    rel = os.path.basename(img_path)
    r = subprocess.run(
        [LARK_CLI, "im", "+messages-send", "--chat-id", CHAT_ID,
         "--as", "bot", "--image", rel],
        capture_output=True, text=True, timeout=60, cwd=cwd,
        env={**os.environ,
              "PATH": os.environ.get("PATH", "") + ":" + os.path.expanduser("~/.bun/bin")},
    )
    if r.returncode != 0:
        print(f"⚠ 飞书大图推送失败: {r.stderr[:200]}", file=sys.stderr)
        return False
    print("✅ 飞书周报大图已推送")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--push", action="store_true", help="推送摘要到飞书群")
    ap.add_argument("--week", type=int, default=0, help="周偏移（0=本周，-1=上周）")
    args = ap.parse_args()

    today = datetime.now().date()
    monday = today - timedelta(days=today.weekday()) + timedelta(weeks=args.week)
    friday = monday + timedelta(days=4)
    days = [(monday + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]
    week_label = f"{monday.strftime('%m/%d')}–{friday.strftime('%m/%d')}"

    days_data = {}
    for d in days:
        mm = load_day(d)
        if mm:
            days_data[d] = mm
    if not days_data:
        print("本周暂无数据")
        sys.exit(0)

    week_cat, week_app, all_segs, day_rows = analyze_week(days_data)
    total = sum(week_cat.values())
    insights = build_insights(week_cat, day_rows, all_segs)

    os.makedirs(REPORT_DIR, exist_ok=True)
    out = os.path.join(REPORT_DIR, f"weekly-{friday.strftime('%Y-%m-%d')}.md")
    md = render_markdown(week_label, week_cat, week_app, day_rows, insights, total)
    with open(out, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"✅ 报告已留档 {out}")

    if args.push:
        summary = render_summary(week_label, week_cat, day_rows, insights, total)
        push_lark(summary)
        # 生成并推送周报大图（显示器友好版）
        try:
            import weekly_dashboard_marathon
            img_path = weekly_dashboard_marathon.render(week_offset=0 if args.week == 0 else args.week)
            if img_path:
                push_lark_image(img_path)
        except Exception as e:
            print(f"⚠ 周报大图生成/推送失败: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
