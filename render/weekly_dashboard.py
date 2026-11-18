#!/usr/bin/env python3
"""周报大图（显示器友好·横向·美观版）。

关键：渲染时用 textbbox 实测每个文本块的边界，保存所有元素矩形，
最后做一次碰撞检测——任意两块相交就报警打印坐标，绝不叠着交付。"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PIL import Image, ImageDraw
from weekly_report import load_day, merge_segments, analyze_week, fmt, pct
from dash_style import load_font
from datetime import datetime, timedelta

W, H = 1920, 1320
M = 64
CATS = ["深度工作", "会议", "沟通协作", "划水", "浏览", "午休", "离开"]

# 配色（美观：柔和灰底 + 黑字 + 高亮黑块）
BG = (248, 248, 250)
INK = (20, 20, 24)
SUB = (105, 105, 115)
MUTED = (150, 150, 158)
CARD = (255, 255, 255)
BORDER = (218, 218, 224)
BAR = (40, 40, 48)

_boxes = []  # 碰撞检测：所有绘制元素的 (x1,y1,x2,y2)


def register(d, xy, text, font, anchor=None):
    """画文字并把其 bbox 记录进 _boxes，用于碰撞检测。"""
    d.text(xy, text, font=font, fill=INK if anchor is None else SUB)
    try:
        x, y = xy
        bbox = d.textbbox((x, y), text, font=font)
        _boxes.append(bbox)
    except Exception:
        pass


def overlap_check():
    """检测任意两个文字块是否相交，打印坐标。"""
    hits = []
    for i in range(len(_boxes)):
        for j in range(i + 1, len(_boxes)):
            a, b = _boxes[i], _boxes[j]
            if a[0] < b[2] and a[2] > b[0] and a[1] < b[3] and a[3] > b[1]:
                hits.append((a, b))
    return hits


def render(week_offset=-1):
    today = datetime.now().date()
    monday = today - timedelta(days=today.weekday()) + timedelta(weeks=week_offset)
    friday = monday + timedelta(days=4)
    days = [(monday + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]
    days_data = {d: load_day(d) for d in days if load_day(d)}
    if not days_data:
        print("本周暂无数据")
        return
    week_cat, week_app, all_segs, day_rows = analyze_week(days_data)
    total = sum(week_cat.values())

    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    F_T = load_font(54)
    F_H2 = load_font(38)
    F_M = load_font(30)
    F_S = load_font(26)
    F_TN = load_font(21)

    y = 40
    # 标题
    register(d, (M, y), "周时间报告", F_T)
    y += 76
    register(d, (M, y), f"{monday.strftime('%m/%d')}–{friday.strftime('%m/%d')} · 共 {len(day_rows)} 天 · 数据源：前台应用+补录", F_S)
    y += 48

    # 三卡
    cards = [("总时长", fmt(total)), ("日均", fmt(total // max(len(day_rows), 1))),
             ("深度工作占比", pct(week_cat.get("深度工作", 0), total) if total else "0%")]
    cx = M
    for label, val in cards:
        d.rounded_rectangle([cx, y, cx + 320, y + 104], radius=18, fill=CARD, outline=BORDER, width=2)
        d.text((cx + 28, y + 20), label, font=F_TN, fill=MUTED)
        d.text((cx + 28, y + 48), val, font=F_T, fill=INK)
        cx += 360
    y += 136

    # 本周分类占比（左栏，宽 880）
    left_x = M
    right_x = M + 920
    ly = y
    d.text((left_x, ly), "本周分类占比", font=F_H2, fill=INK)
    ly += 52
    top = sorted(week_cat.items(), key=lambda kv: -kv[1])[:7]
    for cat, mins in top:
        register(d, (left_x, ly), f"{cat}", F_S)
        register(d, (left_x + 140, ly), fmt(mins), F_TN)
        d.rounded_rectangle([left_x + 260, ly + 6, left_x + 260 + 540, ly + 30], radius=4, fill=(235, 235, 240))
        d.rounded_rectangle([left_x + 260, ly + 6, left_x + 260 + int(540 * mins / total), ly + 30], radius=4, fill=BAR)
        register(d, (left_x + 820, ly), pct(mins, total), F_S)
        ly += 50

    # 右侧：洞察（右栏，宽 ~ 900）
    ry = y
    d.text((right_x, ry), "洞察", font=F_H2, fill=INK)
    ry += 52
    deep = week_cat.get("深度工作", 0)
    shui = week_cat.get("划水", 0)
    meet = week_cat.get("会议", 0) + week_cat.get("沟通协作", 0)
    worst = max(day_rows, key=lambda r: r["n_segs"])
    focus_day = max(day_rows, key=lambda r: r["focus"])
    insights = [
        f"• 深度工作 {pct(deep, total)}（{fmt(deep)}）",
        f"• 划水 {pct(shui, total)}（{fmt(shui)}）",
        f"• 会议+沟通 {pct(meet, total)}（{fmt(meet)}）",
        f"• 最碎：周{worst['wd']} {worst['n_segs']} 段（{fmt(worst['total'])}）",
        f"• 最长专注：周{focus_day['wd']} {fmt(focus_day['focus'])}",
    ]
    for ins in insights:
        register(d, (right_x, ry), ins, F_S)
        ry += 44

    y = max(ly, ry) + 20
    d.line([M, y, W - M, y], fill=BORDER, width=2)
    y += 20

    # 每日 × 类别矩阵（核心，下方全宽）
    d.text((M, y), "每日观察（各类别时长 · 占比）", font=F_H2, fill=INK)
    y += 52
    col_w = 216
    col_x = M + 150
    d.text((M, y), "日", font=F_TN, fill=MUTED)
    for i, c in enumerate(CATS):
        d.text((col_x + i * col_w, y), c, font=F_TN, fill=MUTED)
    y += 34

    row_h = 76
    for r in day_rows:
        d.rounded_rectangle([M - 10, y - 2, W - M + 10, y + row_h - 8], radius=12, fill=CARD)
        register(d, (M, y + 8), f"周{r['wd']}", F_M)
        register(d, (M, y + 48), r['start'] + "–" + r['end'], F_TN)
        rtotal = r["total"] or 1
        for i, c in enumerate(CATS):
            v = r["cat"].get(c, 0)
            bx = col_x + i * col_w
            register(d, (bx, y + 8), fmt(v), F_S)
            ratio = v / rtotal
            d.rounded_rectangle([bx, y + 48, bx + 180, y + 56], radius=3, fill=(235, 235, 240))
            d.rounded_rectangle([bx, y + 48, bx + int(180 * ratio), y + 56], radius=3, fill=BAR)
        y += row_h

    # 底部口径
    y += 8
    d.text((M, y), "注：总时长剔夜间/下班/午休/长离开；「划水」含现场联调等背景性使用。", font=F_TN, fill=MUTED)

    # ===== 碰撞检测 =====
    hits = overlap_check()
    if hits:
        print(f"⚠ 检测到 {len(hits)} 处文字重叠！坐标如下：")
        for a, b in hits[:12]:
            print(f"  {a} ↔ {b}")

    out = os.path.join(REPORTS, "weekly-dashboard.png")
    img.save(out)
    print(f"✅ 周报大图已生成 {out}")
    return out


if __name__ == "__main__":
    off = int(sys.argv[1]) if len(sys.argv) > 1 else -1
    render(off)
