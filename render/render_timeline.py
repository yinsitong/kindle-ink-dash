#!/usr/bin/env python3
"""看板第 4 页：时间去哪了（垂直时间线，文字标注，自动+手动补录）。

数据源：
- 自动：data/timelog/YYYY-MM-DD.tsv（time_logger.py 每分钟 "HH:MM\tApp"）
- 手动：data/timelog/YYYY-MM-DD.manual.tsv（"HH:MM-HH:MM\t描述"，覆盖自动段）

用法：python3 render_timeline.py [--out data/pages/04-timeline.png]
"""

import argparse
import os
import sys
from collections import defaultdict
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dash_style import (
    W, H, MARGIN, BG, INK, INK_MID, INK_SOFT, CHIP, RULE, TRACK, FILL,
    new_canvas, load_font, draw_dots, draw_header, draw_chip, draw_bar,
    section_header, text_w, divider, footer,
)

from dash_paths import TIMELOG, REPORTS, PAGES  # noqa: E402
LOGDIR = TIMELOG
TOTAL_PAGES = 4
PAGE_NO = 4

CATEGORIES = {
    "深度工作": ["proma", "word", "excel", "powerpoint", "pages", "numbers", "keynote",
               "figma", "sketch", "pencil", "幕布", "mindnote", "xmind", "notion", "obsidian", "typora",
               "cursor", "code", "trae", "terminal", "iterm", "xcode"],
    "沟通协作": ["lark", "feishu", "飞书", "dingtalk", "钉钉", "企业微信", "wecom", "mail", "邮件"],
    "会议": ["zoom", "teams", "腾讯会议", "voov", "facetime"],
    "浏览": ["safari", "chrome", "arc", "edge", "firefox", "brave"],
    "划水": ["wechat", "微信", "qq", "bilibili", "哔哩", "douyin", "抖音", "weibo", "微博", "xiaohongshu", "小红书"],
}


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


def hhmm_to_min(s):
    hh, mm = s.split(":")
    return int(hh) * 60 + int(mm)



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

def load_segments(day):
    """返回 [(start_min, end_min, 名称, 类别, 是否手动)]，手动覆盖自动。"""
    auto = {}   # minute -> (app, cat)
    manual = [] # (start, end, text)
    auto_path = os.path.join(LOGDIR, day + ".tsv")
    if os.path.exists(auto_path):
        for line in open(auto_path, encoding="utf-8", errors="ignore"):
            parts = line.rstrip("\n").split("\t")
            if len(parts) != 2:
                continue
            try:
                m = hhmm_to_min(parts[0])
            except ValueError:
                continue
            app = parts[1]
            auto[m] = (app, cat_with_nap(app, "离开" if app == "离开" else categorize(app), m), False)
    manual_path = os.path.join(LOGDIR, day + ".manual.tsv")
    if os.path.exists(manual_path):
        for line in open(manual_path, encoding="utf-8", errors="ignore"):
            parts = line.rstrip("\n").split("\t")
            if len(parts) != 2 or "-" not in parts[0]:
                continue
            try:
                s, e = parts[0].split("-")
                s, e = hhmm_to_min(s), hhmm_to_min(e)
            except ValueError:
                continue
            manual.append((s, e, parts[1].strip()))
    # 分钟表：手动覆盖自动
    minute_map = dict(auto)
    for s, e, text in manual:
        for m in range(s, e):
            minute_map[m] = (text, categorize_manual(text), True)
    if not minute_map:
        return []
    # 合并连续同类段
    segs = []
    for m in sorted(minute_map):
        app, cat, manual_flag = minute_map[m]
        if segs and segs[-1][1] == m and segs[-1][2] == app and segs[-1][4] == manual_flag:
            segs[-1][1] = m + 1
        else:
            segs.append([m, m + 1, app, cat, manual_flag])
    return segs


def cluster_segments(segs, min_dur=15):
    """连续短段（<min_dur 分钟）聚成一簇，只出一个汇总标签。
    手动补录段和 >=min_dur 的段保持独立；离开小段也进簇。"""
    out = []
    i = 0
    while i < len(segs):
        s, e, app, cat, mf = segs[i]
        if mf or (e - s) >= min_dur:
            out.append([s, e, app, cat, mf, None])
            i += 1
            continue
        cs, ce, n = s, e, 1
        apps = defaultdict(int)
        apps[app] += e - s
        j = i + 1
        while j < len(segs):
            s2, e2, app2, cat2, mf2 = segs[j]
            if mf2 or (e2 - s2) >= min_dur:
                break
            apps[app2] += e2 - s2
            ce = e2
            n += 1
            j += 1
        top = sorted(apps.items(), key=lambda kv: -kv[1])
        names = " · ".join(a for a, _ in top[:2])
        label = f"{names} 等{n}段" if n > 2 else names
        out.append([cs, ce, label, "碎段", False, top])
        i = j
    return out


def insert_gaps(segs, gap_min=10):
    """相邻段空洞 > gap_min 分钟 → 插入「无记录」段（Mac 休眠/关机）"""
    out = []
    prev_end = None
    for seg in segs:
        if prev_end is not None and seg[0] - prev_end > gap_min:
            out.append([prev_end, seg[0], "无记录（Mac 休眠）", "空洞", False, None])
        out.append(seg)
        prev_end = seg[1]
    return out


def fit(d, text, font, max_w):
    if d.textlength(text, font=font) <= max_w:
        return text
    while text and d.textlength(text + "…", font=font) > max_w:
        text = text[:-1]
    return text + "…"


def pct(part, whole):
    return f"{part / whole * 100:.0f}%" if whole else "0%"


def fmt_dur(mins):
    if mins < 60:
        return f"{mins}m"
    return f"{mins // 60}h{mins % 60:02d}m"


def render(out_path):
    now = datetime.now()
    day = now.strftime("%Y-%m-%d")
    segs = load_segments(day)
    raw_seg_count = len(segs)

    # 统计（分钟数）
    cat_min = defaultdict(int)
    for s, e, app, cat, _ in segs:
        if cat in ("夜间", "下班"):
            continue
        if cat == "离开" and e - s >= 45:
            continue  # 长离开（>=45 分钟）= 不在电脑前，不计入
        cat_min[cat] += e - s
    total = sum(cat_min.values())

    img, d = new_canvas()

    # ===== 顶部：统一标题栏 =====
    f_small, f_ev = load_font(28, "regular"), load_font(42, "medium")
    today_str = now.strftime("%m/%d 周") + "一二三四五六日"[now.weekday()]
    y = draw_header(d, "时间去哪了", PAGE_NO, TOTAL_PAGES)

    # 概览状态条：今日累计 + 段数
    total_now = sum(cat_min.values())
    y = draw_chip(d, y, "今日累计",
                  f"{today_str} · {total_now / 60:.1f}h · {raw_seg_count} 段")
    y += 30

    # ===== 分类时长排行（圆角条，与额度页一致） =====
    f_cat, f_dur = load_font(36, "regular"), load_font(42, "semibold")
    ranked = sorted(cat_min.items(), key=lambda kv: -kv[1])
    if ranked:
        max_min = ranked[0][1]
        total_min = max(sum(cat_min.values()), 1)
        bar_w = W - MARGIN * 2
        for cat, mins in ranked[:4]:
            label = "补录" if cat == "手动" else cat
            # 第一行：左分类名（灰）+ 右时长与占比（深色），基线对齐
            d.text((MARGIN, y + 6), label, font=f_cat, fill=INK_MID)
            dur = f"{fmt_dur(mins)}   {pct(mins, total_min)}"
            d.text((W - MARGIN - text_w(d, dur, f_dur), y - 2), dur,
                   font=f_dur, fill=INK)
            # 文字与进度条之间留出明确间距，避免压在一起
            y += 76
            draw_bar(d, MARGIN, y, bar_w, 16, mins / max_min * 100)
            y += 26
            # 条与下一条之间再留呼吸空间
            y += 24
    y = divider(d, y + 6, gap=34)

    # ===== 垂直时间轴（聚焦近 4 小时） =====
    f_time, f_ev, f_small, f_cat = load_font(36), load_font(46), load_font(32), load_font(30)
    WINDOW = 240  # 最近 4 小时
    now_min = now.hour * 60 + now.minute + 1
    win_start = now_min - WINDOW
    segs = [s for s in segs if s[1] > win_start]  # 窗口外的丢弃
    segs = insert_gaps(cluster_segments(segs))  # 碎段聚簇 + 空洞标注
    if not segs:
        msg = "近 4 小时暂无记录"
        f_big = load_font(64)
        w = d.textlength(msg, font=f_big)
        d.text(((W - w) / 2, y + 120), msg, font=f_big, fill=140)
    else:
        # 起点收紧：不画大段无数据的空白（最早段前留 30 分钟缓冲）
        t0 = max(win_start, min(s for s, *_ in segs) - 30)
        t1 = max(now_min, max(e for _, e, *_ in segs))
        span = max(t1 - t0, 60)
        # 截断跨越窗口起点的第一段
        if segs[0][0] < t0:
            segs[0][0] = t0
        y_top = y + 8
        y_bottom = H - 120  # 底部留给页脚
        px_per_min = (y_bottom - y_top) / span

        x_rail = MARGIN + 100
        # 小时刻度（仅画窗口内的整点）
        first_tick = t0 // 60 if t0 % 60 == 0 else t0 // 60 + 1
        for hh in range(first_tick, t1 // 60 + 1):
            yy = y_top + (hh * 60 - t0) * px_per_min
            d.line([(x_rail - 12, yy), (x_rail, yy)], fill=0, width=2)
            d.text((MARGIN, yy - 18), f"{hh:02d}", font=f_time, fill=120)
        d.line([(x_rail, y_top), (x_rail, y_bottom)], fill=0, width=3)

        x_box = x_rail + 30
        box_w = W - MARGIN - x_box
        for seg in segs:
            s, e, app, cat, manual_flag = seg[0], seg[1], seg[2], seg[3], seg[4]
            breakdown = seg[5] if len(seg) > 5 else None
            yy0 = y_top + (s - t0) * px_per_min
            yy1 = y_top + (e - t0) * px_per_min
            h = yy1 - yy0
            label = f"{app}{'（补）' if manual_flag else ''}"
            meta = f"{s // 60:02d}:{s % 60:02d}–{e // 60:02d}:{e % 60:02d} · {fmt_dur(e - s)}"
            stale = (now_min - e) > 120  # 距当前超 2 小时的段：弱化
            ink = 150 if stale else 0
            ink_meta = 180 if stale else 120
            if cat == "空洞":
                # 无记录空洞：浅灰细框，文字居中（放不下就不画字）
                d.rectangle([x_box, yy0 + 2, x_box + box_w, yy1 - 2], outline=224, width=2)
                if h >= 44:
                    w_g = d.textlength(label, font=f_small)
                    d.text((x_box + (box_w - w_g) / 2, yy0 + (h - 34) / 2),
                           label, font=f_small, fill=200)
                continue

            # 统一圆角卡片：块高足够则框内排文字，否则退化为实心条
            if h >= 118:
                d.rounded_rectangle([x_box, yy0 + 3, x_box + box_w, yy1 - 3],
                                    radius=12, outline=ink, width=3)
                d.text((x_box + 24, yy0 + 18), fit(d, label, f_ev, box_w - 60),
                       font=f_ev, fill=ink)
                d.text((x_box + 24, yy0 + 70), meta, font=f_small, fill=ink_meta)
                if breakdown and h >= 210:
                    for bi, (bapp, bmin) in enumerate(breakdown[:3]):
                        bt = f"· {bapp}  {fmt_dur(bmin)}"
                        ly = yy0 + 112 + bi * 38
                        if ly + 32 < yy1 - 12:      # 留足行高，防止越界
                            d.text((x_box + 24, ly),
                                   fit(d, bt, f_small, box_w - 48),
                                   font=f_small, fill=ink_meta)
            elif h >= 46:
                # 中块：圆角细框 + 单行，文字垂直居中
                d.rounded_rectangle([x_box, yy0 + 2, x_box + box_w, yy1 - 2],
                                    radius=10, outline=ink, width=2)
                mid = yy0 + (h - 32) / 2
                d.text((x_box + 20, mid), fit(d, f"{label}  {meta}", f_small, box_w - 48),
                       font=f_small, fill=ink)
            elif h >= 26:
                # 矮块：左侧短色块示意时长占比，右侧文字（避免大面积灰压屏）
                seg_min = max(e - s, 1)
                bar_w_seg = max(38, min(box_w * 0.42, box_w * 0.42))
                d.rounded_rectangle([x_box, yy0 + 1, x_box + bar_w_seg, yy1 - 1],
                                    radius=6, fill=205 if stale else 172)
                tx = x_box + bar_w_seg + 16
                d.text((tx, yy0 + (h - 30) / 2),
                       fit(d, f"{label}  {s // 60:02d}:{s % 60:02d}–{e // 60:02d}:{e % 60:02d}",
                           f_small, W - MARGIN - tx - 8),
                       font=f_small, fill=150 if stale else INK_MID)
            else:
                # 极短段：只画细条，不画字（避免行高不足时文字互相压）
                d.rounded_rectangle([x_box, yy0, x_box + max(10, box_w * 0.25), max(yy1, yy0 + 5)],
                                    radius=3, fill=195 if stale else 140)

        # 现在位置
        x_now_y = y_top + (t1 - t0) * px_per_min
        d.polygon([(x_rail - 10, x_now_y - 12), (x_rail - 10, x_now_y + 12), (x_rail + 8, x_now_y)], fill=0)
        y = y_bottom + 30

    # ===== 底部：统一页脚 =====
    footer(d, f"今日累计 {total / 60:.1f}h · {raw_seg_count} 段 · 近 4 小时明细",
           now.strftime("%H:%M"))

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    img.save(out_path, optimize=True)
    return total, len(segs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(PAGES, "04-timeline.png"))
    args = ap.parse_args()
    total, n_segs = render(args.out)
    print(f"✅ 时间线页已渲染 {args.out}（{total} 分钟，{n_segs} 段）")


if __name__ == "__main__":
    main()
