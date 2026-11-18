#!/usr/bin/env python3
"""周报大图 · Marathon 风格（Y2K 赛博朋克 / Graphic Realism）——深底荧光高亮版。

保留数据逻辑，视觉换成 Marathon：近黑底 + 荧光橙/青/粉 + 斜切几何 + 编号标签 + 粗体大字。
内置 textbbox 碰撞自检（文字块相交就报警）。"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PIL import Image, ImageDraw
from weekly_report import load_day, analyze_week, fmt, pct
from dash_style import load_font
from datetime import datetime, timedelta

W, H = 1920, 1440
M = 72
CATS = ["深度工作", "会议", "沟通协作", "划水", "浏览", "午休", "离开"]

# Marathon 配色
BG = (12, 12, 16)          # 近黑
PANEL = (22, 22, 30)       # 面板
INK = (245, 245, 250)      # 亮白
SUB = (150, 150, 165)      # 灰白
ORANGE = (255, 92, 26)     # 荧光橙（主高亮）
CYAN = (0, 229, 255)       # 青
PINK = (255, 61, 166)      # 粉
LIME = (200, 255, 0)       # 黄绿
GRID = (40, 40, 52)        # 网格/分隔线

CAT_COLOR = {"深度工作": ORANGE, "会议": CYAN, "沟通协作": LIME,
             "划水": PINK, "浏览": (150, 150, 165), "午休": (90, 90, 110), "离开": (60, 60, 74)}

_boxes = []


def register(d, xy, text, font, fill):
    d.text(xy, text, font=font, fill=fill)
    try:
        _boxes.append(d.textbbox(xy, text, font=font))
    except Exception:
        pass


def overlap_check():
    hits = []
    for i in range(len(_boxes)):
        for j in range(i + 1, len(_boxes)):
            a, b = _boxes[i], _boxes[j]
            if a[0] < b[2] and a[2] > b[0] and a[1] < b[3] and a[3] > b[1]:
                hits.append((a, b))
    return hits


def slant_bar(d, x, y, w, h, color, slant=10):
    """斜切条（Marathon 标志性斜切几何）。"""
    d.polygon([(x + slant, y), (x + w, y), (x + w - slant, y + h), (x, y + h)], fill=color)


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
    F_HERO = load_font(120)
    F_T = load_font(56)
    F_H2 = load_font(40)
    F_M = load_font(30)
    F_S = load_font(26)
    F_TN = load_font(20)

    # 顶部斜切条（装饰）
    slant_bar(d, M, 30, 360, 14, ORANGE, 14)
    slant_bar(d, M + 380, 30, 200, 14, CYAN, 14)
    slant_bar(d, M + 600, 30, 120, 14, PINK, 14)

    y = 76
    register(d, (M, y), "WEEKLY TIME REPORT", F_HERO, INK)
    y += 156
    register(d, (M, y), f"LOG://WEEK_{monday.strftime('%m%d')}-{friday.strftime('%m%d')}  //  {monday.strftime('%m/%d')}–{friday.strftime('%m/%d')}  ·  {len(day_rows)}D  ·  SOURCE: FOREGROUND+MANUAL", F_S, SUB)
    y += 44

    # 总览三卡（面板）
    cards = [("TOTAL", fmt(total), ORANGE),
             ("DAILY AVG", fmt(total // max(len(day_rows), 1)), CYAN),
             ("DEEP WORK", pct(week_cat.get("深度工作", 0), total) if total else "0%", PINK)]
    cx = M
    for label, val, color in cards:
        d.rounded_rectangle([cx, y, cx + 340, y + 110], radius=10, fill=PANEL, outline=GRID, width=2)
        slant_bar(d, cx, y, 340, 8, color, 8)
        d.text((cx + 26, y + 22), label, font=F_TN, fill=SUB)
        d.text((cx + 26, y + 50), val, font=F_T, fill=INK)
        cx += 380
    y += 150

    # 左：本周分类占比
    lx = M
    rx = M + 920
    ly = y
    d.text((lx, ly), "CATEGORY_BREAKDOWN // 本周分类占比", font=F_H2, fill=ORANGE)
    ly += 56
    top = sorted(week_cat.items(), key=lambda kv: -kv[1])[:7]
    for cat, mins in top:
        col = CAT_COLOR.get(cat, SUB)
        register(d, (lx, ly), cat, F_S, INK)
        register(d, (lx + 150, ly), fmt(mins), F_TN, SUB)
        d.rounded_rectangle([lx + 270, ly + 6, lx + 270 + 560, ly + 30], radius=3, fill=(32, 32, 42))
        d.rounded_rectangle([lx + 270, ly + 6, lx + 270 + int(560 * mins / total), ly + 30], radius=3, fill=col)
        register(d, (lx + 850, ly), pct(mins, total), F_S, INK)
        ly += 52

    # 右：洞察
    ry = y
    d.text((rx, ry), "INSIGHTS // 洞察", font=F_H2, fill=CYAN)
    ry += 56
    deep = week_cat.get("深度工作", 0)
    shui = week_cat.get("划水", 0)
    meet = week_cat.get("会议", 0) + week_cat.get("沟通协作", 0)
    worst = max(day_rows, key=lambda r: r["n_segs"])
    focus_day = max(day_rows, key=lambda r: r["focus"])
    insights = [
        f"▸ 深度工作 {pct(deep, total)}（{fmt(deep)}）",
        f"▸ 划水 {pct(shui, total)}（{fmt(shui)}）",
        f"▸ 会议+沟通 {pct(meet, total)}（{fmt(meet)}）",
        f"▸ 最碎：周{worst['wd']} {worst['n_segs']} 段（{fmt(worst['total'])}）",
        f"▸ 最长专注：周{focus_day['wd']} {fmt(focus_day['focus'])}",
    ]
    for ins in insights:
        register(d, (rx, ry), ins, F_S, INK)
        ry += 46

    y = max(ly, ry) + 24
    d.line([M, y, W - M, y], fill=GRID, width=2)
    y += 24

    # 每日 × 类别矩阵
    d.text((M, y), "DAILY_MATRIX // 每日观察（时长·占比）", font=F_H2, fill=LIME)
    y += 56
    col_w = 216
    col_x = M + 150
    register(d, (M, y), "DAY", F_TN, SUB)
    for i, c in enumerate(CATS):
        register(d, (col_x + i * col_w, y), c, F_TN, SUB)
    y += 36

    row_h = 78
    for r in day_rows:
        d.rounded_rectangle([M - 10, y - 2, W - M + 10, y + row_h - 8], radius=8, fill=PANEL, outline=GRID, width=1)
        register(d, (M, y + 10), f"周{r['wd']}", F_M, INK)
        register(d, (M, y + 52), r['start'] + "–" + r['end'], F_TN, SUB)
        rtotal = r["total"] or 1
        for i, c in enumerate(CATS):
            v = r["cat"].get(c, 0)
            bx = col_x + i * col_w
            register(d, (bx, y + 10), fmt(v), F_S, INK)
            ratio = v / rtotal
            col = CAT_COLOR.get(c, SUB)
            d.rounded_rectangle([bx, y + 50, bx + 180, y + 58], radius=3, fill=(32, 32, 42))
            if ratio > 0:
                d.rounded_rectangle([bx, y + 50, bx + int(180 * ratio), y + 58], radius=3, fill=col)
        y += row_h

    y += 10
    d.text((M, y), "// TOTAL 剔夜间/下班/午休/长离开 · 「划水」含现场联调等背景性使用", font=F_TN, fill=SUB)

    hits = overlap_check()
    if hits:
        print(f"⚠ 检测到 {len(hits)} 处文字重叠：")
        for a, b in hits[:12]:
            print(f"  {a} ↔ {b}")

    out = os.path.join(REPORTS, "weekly-dashboard-marathon.png")
    img.save(out)
    print(f"✅ Marathon 风格周报大图已生成 {out}")
    return out


if __name__ == "__main__":
    off = int(sys.argv[1]) if len(sys.argv) > 1 else -1
    render(off)
