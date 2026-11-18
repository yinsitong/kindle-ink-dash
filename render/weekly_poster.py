#!/usr/bin/env python3
"""周报一图流：把周时间报告画成一张 Kindle 友好竖版信息图（1072×1448）。"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PIL import Image, ImageDraw
from weekly_report import load_day, merge_segments, analyze_week, fmt, pct, WEEKDAYS
from dash_style import load_font, new_canvas, draw_header
from collections import defaultdict
from datetime import datetime, timedelta

W, H = 1080, 1920
MARGIN = 72
GUTTER = W - MARGIN * 2

CAT_COLOR = None  # 灰度海报，用文字+条形表达


def bar(draw, x, y, w_max, ratio, h=30):
    """黑框轨道 + 实心填充。"""
    draw.rectangle([x, y, x + w_max, y + h], outline=0, width=3)
    if ratio > 0:
        draw.rectangle([x + 2, y + 2, x + 2 + int((w_max - 4) * ratio), y + h - 2], fill=0)


def render(week_offset=0):
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

    img = Image.new("L", (W, H), 255)
    d = ImageDraw.Draw(img)
    f_big = load_font(120)
    f_h1 = load_font(76)
    f_h2 = load_font(50)
    f_mid = load_font(42)
    f_small = load_font(34)

    # 自建标题栏（不受 dash_style 固定尺寸影响）
    y = 120
    d.text((MARGIN, y), "周报一图流", font=f_h1, fill=0)
    d.text((MARGIN, y + 110), f"{monday.strftime('%m/%d')}–{friday.strftime('%m/%d')}",
           font=f_mid, fill=90)
    y += 220

    # ===== 总览大数字 =====
    d.text((MARGIN, y), fmt(total), font=f_big, fill=0)
    d.text((MARGIN + d.textlength(fmt(total), font=f_big) + 30, y + 70),
           "总时长", font=f_mid, fill=90)
    d.text((MARGIN, y + 170), f"5 天 · 日均 {fmt(total // max(len(day_rows), 1))}",
           font=f_mid, fill=90)
    y += 290

    # ===== 分类占比 =====
    d.text((MARGIN, y), "分类占比", font=f_h2, fill=0)
    y += 86
    top = sorted(week_cat.items(), key=lambda kv: -kv[1])[:6]
    for cat, mins in top:
        label = f"{cat}  {fmt(mins)} · {pct(mins, total)}"
        d.text((MARGIN, y), label, font=f_mid, fill=0)
        bar(d, MARGIN, y + 62, GUTTER, mins / total, h=30)
        y += 128

    # ===== 每日一览 =====
    y += 20
    d.text((MARGIN, y), "每日一览", font=f_h2, fill=0)
    y += 86
    for r in day_rows:
        d.text((MARGIN, y), f"周{r['wd']}", font=f_small, fill=0)
        d.text((MARGIN + 92, y), f"{r['start']}–{r['end']} · {fmt(r['total'])}  深{fmt(r['cat'].get('深度工作',0))} 会{fmt(r['cat'].get('会议',0)+r['cat'].get('沟通协作',0))} 划{fmt(r['cat'].get('划水',0))}",
               font=f_small, fill=60)
        y += 68

    # ===== 底部备注 =====
    y += 10
    d.line([MARGIN, y, MARGIN + GUTTER, y], fill=0, width=2)
    y += 20
    note = "注：总时长剔夜间/下班/午休/长离开；「划水」含现场联调等背景性使用"
    d.text((MARGIN, y), note, font=f_small, fill=90)

    out = os.path.join(REPORTS, "weekly-poster.png")
    img.save(out)
    print(f"✅ 周报一图流已生成 {out}")
    return out


if __name__ == "__main__":
    off = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    render(off)
