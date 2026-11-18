#!/usr/bin/env python3
"""查询模型额度并渲染成 Kindle PW3 额度页（1072x1348，顶部 100px 留给原生状态栏）。

版式与其余三页统一：标题行 + 页码点 → 概览状态条 → 内容 → 页脚。
语义：进度条与百分比一律表示「已使用 / 总额度」。

用法：
    export DEEPSEEK_API_KEY=... KIMI_CODING_API_KEY=...
    python3 kindle_quota_render.py [--out /path/to/quota.png]
"""

import argparse
import os
import sys
from datetime import datetime, timezone, timedelta

from PIL import ImageDraw  # noqa: F401  （保留以便调试）

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dash_paths import QUOTA_MODULE_DIR  # noqa: E402

# 额度查询实现是可插拔的：QUOTA_MODULE_DIR 指向一个含 dot_quota_monitor.py
# （提供 query_deepseek / query_kimi）的目录。不配置时本页显示 N/A，
# 其余三页完全不受影响——这不是必需依赖。
query_deepseek = query_kimi = None
if QUOTA_MODULE_DIR and os.path.isdir(QUOTA_MODULE_DIR):
    sys.path.insert(0, QUOTA_MODULE_DIR)
    try:
        from dot_quota_monitor import query_deepseek, query_kimi  # noqa: F811
    except Exception:
        query_deepseek = query_kimi = None
from dash_style import (  # noqa: E402
    W, H, MARGIN, BG, INK, INK_MID, INK_SOFT, RULE,
    new_canvas, load_font, draw_header, draw_chip, section_header,
    metric_row, draw_bar, bar_caption, divider, footer, text_w,
)

PAGE_NO, TOTAL_PAGES = 1, 4


def render(out_path):
    ds_balance, ds_str = None, "N/A"
    kimi = {"five_h": 0, "week": 0, "reset_5h": "-", "reset_week": "-"}
    errors = []

    if query_deepseek is None or query_kimi is None:
        errors.append("额度模块未配置（见 README · 可选功能）")
    else:
        try:
            ds_balance, ds_str = query_deepseek()
        except Exception as e:
            errors.append(f"DeepSeek: {e}")
        try:
            kimi = query_kimi()
        except Exception as e:
            errors.append(f"Kimi: {e}")

    now_dt = datetime.now(timezone(timedelta(hours=8)))
    now = now_dt.strftime("%m/%d %H:%M")

    img, d = new_canvas()
    f_label = load_font(33, "regular")
    f_val = load_font(70, "semibold")
    f_pct = load_font(56, "semibold")
    f_small = load_font(28, "regular")

    # ① 标题行（与其他三页完全同位置）
    y = draw_header(d, "额度", PAGE_NO, TOTAL_PAGES)

    # ② 概览状态条：最近到期的重置时刻
    y = draw_chip(d, y, "最近到期", f"Kimi · 5 小时窗口 · {kimi['reset_5h']} 重置")
    y += 40

    # ③ DeepSeek 余额
    y = section_header(d, y, "DeepSeek", "账户余额")
    y = metric_row(d, y, "账户余额", f"¥{ds_str}", f_label, f_val)
    y = divider(d, y + 6)

    # ④ Kimi Coding Plan
    y = section_header(d, y, "Kimi Coding Plan", "Kimi For Coding")
    bar_w = W - MARGIN * 2
    for label, pct, reset in (
        ("每周额度", kimi["week"], f"{kimi['reset_week']} 重置"),
        ("每 5 小时", kimi["five_h"], f"{kimi['reset_5h']} 重置"),
    ):
        d.text((MARGIN, y + 10), label, font=f_label, fill=INK_MID)
        pct_text = f"{pct}%"
        d.text((W - MARGIN - text_w(d, pct_text, f_pct), y - 8), pct_text,
               font=f_pct, fill=INK)
        y += 84
        draw_bar(d, MARGIN, y, bar_w, 24, pct)
        y += 44
        bar_caption(d, y, reset, f_small)
        y += 68

    # ⑤ 页脚
    footer(d, "进度条显示已使用比例", now_dt.strftime("%H:%M"))
    if errors:
        d.text((MARGIN, H - 128), f"⚠ {errors[0][:44]}", font=f_small, fill=INK)

    img.save(out_path, optimize=True)
    return errors


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/tmp/kindle_quota/quota.png")
    args = ap.parse_args()

    if not os.environ.get("KIMI_CODING_API_KEY") and not os.environ.get("DEEPSEEK_API_KEY"):
        print("Error: 请设置 DEEPSEEK_API_KEY / KIMI_CODING_API_KEY", file=sys.stderr)
        sys.exit(1)

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    errors = render(args.out)
    print(f"✅ 已渲染 {args.out} ({W}x{H})")
    for e in errors:
        print(f"  ⚠ {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
