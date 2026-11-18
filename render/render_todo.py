#!/usr/bin/env python3
"""看板第 3 页：待办（飞书任务 + Proma Todo，逾期反色置顶）。

用法：python3 render_todo.py [--out data/pages/03-todo.png]
"""

import argparse
import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dash_paths import PAGES, LARK_CLI, error_text  # noqa: E402
from dash_style import (
    W, H, MARGIN, BG, INK, INK_MID, INK_SOFT, CHIP, RULE, TRACK, FILL,
    new_canvas, load_font, draw_header, draw_chip, section_header,
    text_w, divider, footer,
)

PLANNING_DB = (os.environ.get("PROMA_PLANNING_DB")
               or os.path.expanduser("~/.proma/planning.db"))
TOTAL_PAGES = 4
PAGE_NO = 3
SOON_DAYS = 3


def fetch_lark_tasks():
    """飞书任务 → [{title, due(datetime|None)}]，只取未完成"""
    try:
        r = subprocess.run(
            [LARK_CLI, "task", "+get-my-tasks", "--format", "json"],
            capture_output=True, text=True, timeout=120,
            env={**os.environ,
                  "PATH": os.environ.get("PATH", "") + ":" + os.path.expanduser("~/.bun/bin")},
        )
        data = json.loads(r.stdout)
        tasks = []
        for item in (data.get("data") or {}).get("items") or []:
            if item.get("completed"):
                continue
            title = (item.get("summary") or "").strip()
            if not title:
                continue
            due = None
            if item.get("due_at"):
                try:
                    due = datetime.fromisoformat(item["due_at"]).replace(tzinfo=None)
                except ValueError:
                    pass
            tasks.append({"title": title, "due": due, "src": "飞书"})
        return tasks, None
    except Exception as e:
        return [], error_text(e)


def fetch_proma_todos():
    """Proma planning.db → 同结构，只取 open"""
    try:
        conn = sqlite3.connect(f"file:{PLANNING_DB}?mode=ro", uri=True)
        rows = conn.execute(
            "SELECT title, due_at, priority FROM todos WHERE status='open'"
        ).fetchall()
        conn.close()
        tasks = []
        for title, due_at, priority in rows:
            due = None
            if due_at:
                ts = due_at / 1000 if due_at > 1e12 else due_at
                try:
                    due = datetime.fromtimestamp(ts)
                except (OSError, OverflowError):
                    pass
            tasks.append({"title": title, "due": due, "src": "P"})
        return tasks, None
    except Exception as e:
        return [], error_text(e)


def classify(tasks):
    now = datetime.now()
    soon_end = now + timedelta(days=SOON_DAYS)
    overdue, soon, rest = [], [], []
    for t in tasks:
        if t["due"] and t["due"] < now:
            overdue.append(t)
        elif t["due"] and t["due"] <= soon_end:
            soon.append(t)
        else:
            rest.append(t)
    overdue.sort(key=lambda t: t["due"])
    soon.sort(key=lambda t: t["due"])
    rest.sort(key=lambda t: (t["due"] is None, t["due"] or datetime.max))
    return overdue, soon, rest


def render(out_path):
    lark, err_l = fetch_lark_tasks()
    proma, err_p = fetch_proma_todos()
    errors = [e for e in (err_l, err_p) if e]
    overdue, soon, rest = classify(lark + proma)

    img, d = new_canvas()
    f_ev = load_font(41, "light")
    f_small = load_font(28, "regular")
    f_tag = load_font(26, "regular")
    f_big = load_font(64, "medium")

    now = datetime.now()
    total = len(overdue) + len(soon) + len(rest)
    y = draw_header(d, "待办", PAGE_NO, TOTAL_PAGES)

    def fit_text(text, max_w, font):
        if d.textlength(text, font=font) <= max_w:
            return text
        while text and d.textlength(text + "…", font=font) > max_w:
            text = text[:-1]
        return text + "…"

    # 概览状态条：左「本期待办」，右逾期/今日到期统计
    right_bits = []
    if overdue:
        right_bits.append(f"逾期 {len(overdue)}")
    if soon:
        right_bits.append(f"{SOON_DAYS} 天内 {len(soon)}")
    if not right_bits:
        right_bits.append("暂无紧急项")
    y = draw_chip(d, y, "本期待办", " · ".join(right_bits) + f" · 共 {total} 项")
    y += 30

    def row(t, y, kind):
        """待办行：左状态标记 + 标题，右侧日期与来源。"""
        title = t["title"]
        src_tag = f"[{t['src']}]"
        due_str = t["due"].strftime("%m/%d") if t["due"] else ""
        right = f"{due_str} {src_tag}".strip()

        # 状态标记：逾期用实心点 + 深色，其余用空心圆圈
        cx, cy = MARGIN + 10, y + 24
        if kind == "overdue":
            d.ellipse([cx - 9, cy - 9, cx + 9, cy + 9], fill=INK)
        elif kind == "soon":
            d.ellipse([cx - 9, cy - 9, cx + 9, cy + 9], outline=INK_MID, width=3)
            d.ellipse([cx - 3, cy - 3, cx + 3, cy + 3], fill=INK_MID)
        else:
            d.ellipse([cx - 9, cy - 9, cx + 9, cy + 9], outline=INK_SOFT, width=2)

        text_x = MARGIN + 40
        tw_right = text_w(d, right, f_small) + 16
        d.text((text_x, y + 6), fit_text(title, W - MARGIN - text_x - tw_right, f_ev),
               font=f_ev, fill=INK)
        d.text((W - MARGIN - text_w(d, right, f_small), y + 12), right,
               font=f_small, fill=INK_MID)
        return y + 80

    # 已逾期
    if overdue:
        y = section_header(d, y, "已逾期", f"{len(overdue)} 项")
        y -= 22
        for t in overdue[:4]:
            if y > H - 210:
                break
            y = row(t, y, "overdue")
        if len(overdue) > 4:
            d.text((MARGIN + 40, y + 2), f"…还有 {len(overdue) - 4} 项逾期",
                   font=f_small, fill=INK_SOFT)
            y += 56
        y += 12

    # 即将到期
    if soon:
        y = section_header(d, y, f"{SOON_DAYS} 天内到期", f"{len(soon)} 项")
        y -= 22
        for t in soon[:5]:
            if y > H - 210:
                break
            y = row(t, y, "soon")
        y += 12

    # 其他待办（填满剩余空间）
    if rest and y < H - 250:
        y = section_header(d, y, "其他待办", f"共 {len(rest)} 项")
        y -= 22
        shown = 0
        for t in rest:
            if y > H - 210:
                break
            y = row(t, y, "rest")
            shown += 1
        if len(rest) > shown:
            d.text((MARGIN + 40, y + 2), f"…还有 {len(rest) - shown} 项",
                   font=f_small, fill=INK_SOFT)

    if total == 0:
        msg = "全部搞定 🎉"
        d.text(((W - text_w(d, msg, f_big)) / 2, y + 120), msg, font=f_big, fill=INK_SOFT)

    footer(d, "飞书任务 + Proma 待办", now.strftime("%H:%M"))
    if errors:
        d.text((MARGIN, H - 128), "⚠ " + "；".join(errors)[:40], font=f_small, fill=INK)

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    img.save(out_path, optimize=True)
    return len(overdue), len(soon), len(rest), errors


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(PAGES, "03-todo.png"))
    args = ap.parse_args()
    n_over, n_soon, n_rest, errors = render(args.out)
    print(f"✅ 待办页已渲染 {args.out}（逾期 {n_over}，将到期 {n_soon}，其他 {n_rest}）")
    for e in errors:
        print(f"  ⚠ {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
