#!/usr/bin/env python3
"""看板第 2 页：今日日程（Apple 日历 + 飞书日历合并去重）。

视觉：浅米白底卡片式，与额度页统一——日期块、进行中高亮、分组标题、细分隔线。

用法：python3 render_schedule.py [--out data/pages/02-schedule.png]
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dash_paths import PAGES, LARK_CLI, error_text  # noqa: E402
from dash_style import (  # noqa: E402
    W, H, MARGIN, BG, INK, INK_MID, INK_SOFT, CHIP, RULE,
    new_canvas, load_font, draw_header, draw_chip, section_header,
    text_w, divider, footer, fit as fit_text,
)

AS_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "apple_events.applescript")
TOTAL_PAGES = 4
PAGE_NO = 2
WEEKDAYS = "一二三四五六日"
NOW = datetime.now()

HILITE = 238   # 进行中高亮底色
BAR = 118      # 事件左侧色条


def fetch_apple():
    """Apple 日历 → [{start, end, allday, cal, title}]"""
    try:
        r = subprocess.run(["osascript", AS_SCRIPT], capture_output=True, text=True, timeout=90)
        events = []
        for line in r.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) < 5:
                continue
            try:
                start = datetime.strptime(parts[0], "%Y-%m-%d %H:%M")
                end = datetime.strptime(parts[1], "%Y-%m-%d %H:%M")
            except ValueError:
                continue
            events.append({"start": start, "end": end, "allday": parts[2] == "true",
                           "cal": parts[3], "title": parts[4].strip()})
        return events, None
    except Exception as e:
        return [], error_text(e)


def fetch_lark():
    """飞书日历 → 同结构"""
    try:
        today = datetime.now().strftime("%Y-%m-%d 00:00")
        day2 = (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d 00:00")
        r = subprocess.run(
            [LARK_CLI, "calendar", "+agenda", "--start", today, "--end", day2, "--format", "json"],
            capture_output=True, text=True, timeout=120,
            env={**os.environ,
                  "PATH": os.environ.get("PATH", "") + ":" + os.path.expanduser("~/.bun/bin")},
        )
        data = json.loads(r.stdout)
        events = []
        for item in data.get("data") or []:
            s = (item.get("start_time") or {}).get("datetime", "")
            e = (item.get("end_time") or {}).get("datetime", "")
            title = (item.get("summary") or "").strip()
            if not s or not title:
                continue
            try:
                start = datetime.fromisoformat(s).replace(tzinfo=None)
                end = datetime.fromisoformat(e).replace(tzinfo=None) if e else start
            except ValueError:
                continue
            allday = start.hour == 0 and start.minute == 0 and (end - start) >= timedelta(hours=23)
            events.append({"start": start, "end": end, "allday": allday,
                           "cal": "飞书", "title": title})
        return events, None
    except Exception as e:
        return [], error_text(e)


def dedupe(events):
    """按 (标题, 日期时分) 去重——Apple 订阅的飞书日历和飞书 API 会重复"""
    seen = {}
    for ev in events:
        key = (ev["title"].replace(" ", ""), ev["start"].strftime("%Y%m%d%H%M"))
        if key not in seen:
            seen[key] = ev
    return sorted(seen.values(), key=lambda x: x["start"])


def fit(d, text, font, max_w):
    if d.textlength(text, font=font) <= max_w:
        return text
    while text and d.textlength(text + "…", font=font) > max_w:
        text = text[:-1]
    return text + "…"


def event_row(d, x, y, ev, now, allow_ongoing=True, row_h=112):
    """事件行：左时间列 + 竖色条 + 标题；进行中整行浅底高亮。返回下一个 y。"""
    f_time = load_font(40, "medium")
    f_end = load_font(28, "regular")
    f_title = load_font(42, "medium")
    f_tag = load_font(27, "regular")

    ongoing = allow_ongoing and ev["start"] <= now < ev["end"] and not ev["allday"]
    if ongoing:
        d.rounded_rectangle([x - 18, y - 12, W - MARGIN + 18, y + row_h - 14],
                            radius=14, fill=HILITE)

    if ev["allday"]:
        d.rounded_rectangle([x, y + 8, x + 96, y + 60], radius=10, fill=INK)
        d.text((x + 18, y + 18), "全天", font=f_tag, fill=BG)
        d.text((x + 124, y + 14), fit(d, ev["title"], f_title, W - MARGIN - x - 140),
               font=f_title, fill=INK)
        return y + row_h

    # 左侧竖色条
    d.rounded_rectangle([x, y + 6, x + 8, y + row_h - 22], radius=4, fill=INK_SOFT)
    # 时间列
    d.text((x + 30, y + 4), ev["start"].strftime("%H:%M"), font=f_time, fill=INK)
    d.text((x + 32, y + 60), ev["end"].strftime("%H:%M"), font=f_end, fill=INK_SOFT)

    tx = x + 236
    tag_w = text_w(d, "进行中", f_tag) + 32 if ongoing else 0
    d.text((tx, y + 24), fit(d, ev["title"], f_title, W - MARGIN - tx - tag_w - 10),
           font=f_title, fill=INK)
    if ongoing:
        d.rounded_rectangle([W - MARGIN - tag_w, y + 22, W - MARGIN, y + 62],
                            radius=8, fill=INK)
        d.text((W - MARGIN - tag_w + 16, y + 29), "进行中", font=f_tag, fill=BG)
    return y + row_h


def render(out_path):
    apple, err_a = fetch_apple()
    lark, err_l = fetch_lark()
    events = dedupe(apple + lark)
    errors = [e for e in (err_a, err_l) if e]

    now = datetime.now()
    today = now.date()
    tomorrow = today + timedelta(days=1)
    today_ev = [e for e in events if e["start"].date() == today]
    tomorrow_ev = [e for e in events if e["start"].date() == tomorrow]

    img, d = new_canvas()
    f_small = load_font(28, "regular")

    # ① 标题行（与其余三页同位置）
    y = draw_header(d, "日程", PAGE_NO, TOTAL_PAGES)

    # ② 概览状态条：日期 + 项数 + 进行中
    ongoing = [e for e in today_ev if not e["allday"] and e["start"] <= now < e["end"]]
    sub_right = tmr_head = now.strftime("%m/%d 周") + WEEKDAYS[now.weekday()] + f" · 共 {len(today_ev)} 项"
    if ongoing:
        sub_right += f" · 进行中 {ongoing[0]['title'][:8]}"
    y = draw_chip(d, y, "今日日程", sub_right)
    y += 34

    # ③ 今日事件（动态行高，项多时压缩，保证明日区块与服务区可见）
    footer_top = H - 78 - 20
    sec_h = 34 + 46
    avail_total = footer_top - y

    if not today_ev:
        msg = "今天没有日程"
        f_big = load_font(60, "medium")
        d.text(((W - text_w(d, msg, f_big)) / 2, y + 90), msg, font=f_big, fill=INK_SOFT)
        y += 240
        row_h = 112
    else:
        row_h = 112
        if tomorrow_ev:
            budget = avail_total - 44
            row_h = min(112, int(budget / max(len(today_ev), 1)) - 2)
            row_h = max(row_h, 78)
        for ev in today_ev:
            y = event_row(d, MARGIN, y, ev, now, row_h=row_h)

    # ④ 明天
    tmr = now + timedelta(days=1)
    sub_head = tmr.strftime("%m/%d 周") + WEEKDAYS[tmr.weekday()]
    need_full = 76 + 112 * min(len(tomorrow_ev), 2) + 44
    avail = footer_top - (y + 12)

    if tomorrow_ev and avail >= need_full:
        y = divider(d, y + 12, gap=40)
        d.text((MARGIN, y - 8), "明天", font=load_font(40, "semibold"), fill=INK)
        sub = sub_head + f" · {len(tomorrow_ev)} 项"
        d.text((W - MARGIN - text_w(d, sub, f_small), y + 4), sub,
               font=f_small, fill=INK_SOFT)
        y += 72
        for ev in tomorrow_ev[:2]:
            y = event_row(d, MARGIN, y, ev, now, allow_ongoing=False)
        if len(tomorrow_ev) > 2:
            d.text((MARGIN + 30, y + 2), f"…还有 {len(tomorrow_ev) - 2} 项",
                   font=f_small, fill=INK_SOFT)
    elif tomorrow_ev:
        y = divider(d, min(y + 12, footer_top - 76), gap=32)
        d.text((MARGIN, y - 8), "明天", font=load_font(34, "semibold"), fill=INK)
        first = tomorrow_ev[0]
        line = f"{sub_head} · {len(tomorrow_ev)} 项 · "
        line += ("全天 " + first["title"]) if first["allday"] else \
            (first["start"].strftime("%H:%M") + " " + first["title"])
        d.text((MARGIN + 100, y - 4), fit_text(d, line, f_small, W - MARGIN * 2 - 100),
               font=f_small, fill=INK_MID)

    footer(d, "合并 Apple 日历与飞书日历", now.strftime("%H:%M"))
    if errors:
        d.text((MARGIN, H - 128), "⚠ " + "；".join(errors)[:40], font=f_small, fill=INK)

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    img.save(out_path, optimize=True)
    return len(today_ev), len(tomorrow_ev), errors


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(PAGES, "02-schedule.png"))
    args = ap.parse_args()
    n_today, n_tmr, errors = render(args.out)
    print(f"✅ 日程页已渲染 {args.out}（今天 {n_today} 项，明天 {n_tmr} 项）")
    for e in errors:
        print(f"  ⚠ {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
