#!/usr/bin/env python3
"""用飞书「妙记」自动补录会议时间。

背景
- 飞书日历里的日程是用户自己排的「每时段做什么」时间规划块，vc_type=vc 只是创建方式，
  不代表真的开过会。
- timelog 只采前台 App：开会时不敲键鼠会被判成「离开」，而 weekly_report 会丢弃
  ≥45 分钟的连续离开，于是会议时间在周报里凭空消失。
- 妙记（Minutes）每次录音都有真实起止时间和 AI 摘要，是会议时间的权威来源，含线下会议。

本脚本做的事
1. `lark-cli minutes +search --owner-ids me` 拉取指定周的妙记
2. 按起止时间生成会议时段，去掉重复上传的同名同时间段记录
3. 用 AI 摘要生成可读标题，写入 timelog/YYYY-MM-DD.manual.tsv（格式 HH:MM-HH:MM<TAB>描述）
4. 幂等：已存在的补录时段（重叠 ≥60%）不重复写入，手工命名过的条目不会被覆盖

用法
  python3 minutes_annotate.py                # 本周（周一~周五）
  python3 minutes_annotate.py --week -1      # 上周
  python3 minutes_annotate.py --include-weekend   # 含周六周日
  python3 minutes_annotate.py --dry-run      # 只打印将要写入的内容
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta

from dash_paths import TIMELOG, REPORTS, PAGES  # noqa: E402
LOGDIR = TIMELOG
from dash_paths import LARK_CLI  # noqa: E402
MEETING_KEYWORDS = ("会议", "开会", "评审", "例会", "沟通")
# 摘要里需要剥掉的开头词（长词优先匹配）与截断标记
STRIP_HEAD = ("音频围绕", "视频围绕", "音频同步了", "音频明确", "视频明确",
              "本次", "音频", "视频", "录音", "围绕", "同步了", "同步",
              "明确了", "明确", "讨论了", "讨论", "梳理了", "针对")
CUT_MARKS = ("相关内容", "展开沟通", "展开", "，", ",", "。", "；", "：", ":", "\n", "-")


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"命令失败: {' '.join(cmd)}\n{r.stderr[:400]}")
    return r.stdout


def week_range(offset: int, include_weekend: bool):
    today = datetime.now()
    monday = (today - timedelta(days=today.weekday()) + timedelta(weeks=offset)).date()
    last = monday + timedelta(days=6 if include_weekend else 4)
    return monday, last


def fetch_minutes(start, end):
    """拉取时间范围内的全部妙记（含分页）。"""
    items, token = [], None
    while True:
        cmd = [LARK_CLI, "minutes", "+search", "--owner-ids", "me",
               "--start", str(start), "--end", str(end), "--page-size", "30", "--json"]
        if token:
            cmd += ["--page-token", token]
        raw = run(cmd)
        payload = json.loads(raw[raw.index("{"):])
        data = payload.get("data") or {}
        items.extend(data.get("items") or [])
        if not data.get("has_more") or not data.get("page_token"):
            break
        token = data["page_token"]
    return items


def parse_meta(item):
    """从 display_info / description 里取开始时间与时长（秒）。"""
    text = item.get("meta_data", {}).get("description") or item.get("display_info", "")
    m = re.search(r"开始时间:\s*(\d{4})\.(\d{2})\.(\d{2})\s+(\d{2}):(\d{2}):(\d{2})", text)
    if not m:
        return None
    start = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                     int(m.group(4)), int(m.group(5)), int(m.group(6)))
    d = re.search(r"时长:\s*(?:(\d+)\s*小时)?\s*(?:(\d+)\s*分)?\s*(?:(\d+)\s*秒)?", text)
    secs = 0
    if d:
        secs = int(d.group(1) or 0) * 3600 + int(d.group(2) or 0) * 60 + int(d.group(3) or 0)
    if secs <= 0:
        return None
    return start, secs, item.get("token", "")


def fetch_summaries(tokens):
    """批量取 AI 摘要，token → 摘要首段。失败不影响主流程。"""
    out = {}
    for i in range(0, len(tokens), 10):
        chunk = tokens[i:i + 10]
        try:
            raw = run([LARK_CLI, "minutes", "+detail", "--minute-tokens", ",".join(chunk),
                       "--summary", "--json"])
            payload = json.loads(raw[raw.index("{"):])
            for m in (payload.get("data") or {}).get("minutes") or []:
                s = ((m.get("artifacts") or {}).get("summary") or "").strip()
                if s:
                    out[m["minute_token"]] = s
        except Exception as e:
            print(f"  ⚠️ 摘要获取失败（{len(chunk)} 条）: {str(e)[:80]}")
    return out


def make_title(summary: str) -> str:
    """把摘要首段压成 ≤22 字的可读标题。"""
    line = summary.split("\n")[0]
    line = re.sub(r"[*#>`]", "", line).strip()
    # 反复剥掉开头噪声词
    changed = True
    while changed:
        changed = False
        for w in STRIP_HEAD:
            if line.startswith(w):
                line = line[len(w):].lstrip("了").strip(" ，。、：")
                changed = True
                break
    for mark in CUT_MARKS:
        idx = line.find(mark)
        if idx >= 4:
            line = line[:idx]
            break
    line = line.strip(" ，。、：;-").rstrip("及与和")
    if len(line) > 22:
        # 优先在顿号/空格处断开，避免截断半个词
        for sep in ("、", " ", "与", "及"):
            idx = line.rfind(sep, 8, 23)
            if idx > 0:
                line = line[:idx]
                break
        else:
            line = line[:22]
    return line.strip(" ，。、").rstrip("及与和") or "会议录音"


def read_manual(path):
    """返回 [(start_min, end_min, text)]。"""
    rows = []
    if not os.path.exists(path):
        return rows
    for line in open(path, encoding="utf-8", errors="ignore"):
        parts = line.rstrip("\n").split("\t")
        if len(parts) != 2 or "-" not in parts[0]:
            continue
        try:
            s, e = parts[0].split("-")
            sh, sm = s.split(":"); eh, em = e.split(":")
            rows.append((int(sh) * 60 + int(sm), int(eh) * 60 + int(em), parts[1].strip()))
        except ValueError:
            continue
    return rows


def overlap(a0, a1, b0, b1):
    return max(0, min(a1, b1) - max(a0, b0))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--week", type=int, default=0, help="周偏移，0=本周")
    ap.add_argument("--include-weekend", action="store_true", help="统计含周六周日")
    ap.add_argument("--dry-run", action="store_true", help="只打印不写入")
    args = ap.parse_args()

    start, end = week_range(args.week, args.include_weekend)
    print(f"📅 妙记补录范围：{start} ~ {end}")
    try:
        items = fetch_minutes(start, end)
    except Exception as e:
        print(f"❌ 拉取妙记失败：{str(e)[:200]}")
        return 1
    sessions = [parse_meta(it) for it in items]
    sessions = [s for s in sessions if s]
    sessions.sort(key=lambda x: x[0])
    print(f"   原始妙记 {len(items)} 条，有效 {len(sessions)} 条")

    # 去重：同一起始时间（±2 分钟）视为同一次会议重复上传
    dedup = []
    for s in sessions:
        if dedup and abs((s[0] - dedup[-1][0]).total_seconds()) <= 120:
            if s[1] > dedup[-1][1]:      # 保留更长的那条
                dedup[-1] = s
            continue
        dedup.append(s)

    # 命名（只为缺摘要的时段取摘要）
    need = [s[2] for s in dedup if s[2]]
    summaries = fetch_summaries(need) if need else {}

    per_day = {}
    for st, secs, tok in dedup:
        day = st.strftime("%Y-%m-%d")
        b0 = st.hour * 60 + st.minute
        b1 = b0 + max(1, round(secs / 60))
        per_day.setdefault(day, []).append((b0, b1, make_title(summaries.get(tok, ""))))

    total_new = 0
    for day in sorted(per_day):
        path = os.path.join(LOGDIR, day + ".manual.tsv")
        existing = read_manual(path)
        added = []
        for b0, b1, title in per_day[day]:
            covered = False
            for e0, e1, etext in existing:
                ov = overlap(b0, b1, e0, e1)
                if ov >= 0.6 * (b1 - b0) and any(k in etext for k in MEETING_KEYWORDS):
                    covered = True
                    break
            if covered:
                print(f"   = {day[5:]} {b0//60:02d}:{b0%60:02d}–{b1//60:02d}:{b1%60:02d} {title}（已存在，跳过）")
                continue
            added.append((b0, b1, title))
            print(f"   + {day[5:]} {b0//60:02d}:{b0%60:02d}–{b1//60:02d}:{b1%60:02d} {title}（会议）")

        if not added or args.dry_run:
            total_new += len(added)
            continue

        rows = existing + [(b0, b1, t + "（会议）") for b0, b1, t in added]
        rows.sort(key=lambda x: x[0])
        with open(path, "w", encoding="utf-8") as f:
            for b0, b1, text in rows:
                f.write(f"{b0//60:02d}:{b0%60:02d}-{b1//60:02d}:{b1%60:02d}\t{text}\n")
        total_new += len(added)

    verb = "将写入" if args.dry_run else "已写入"
    print(f"✅ {verb} {total_new} 条会议补录")
    return 0


if __name__ == "__main__":
    sys.exit(main())
