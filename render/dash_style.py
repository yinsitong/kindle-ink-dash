"""看板四页共用的视觉规范：画布、字体、页码点、卡片、进度条、明细行。

版式统一约定（四页完全一致，2026-11-17）：
    ① 标题行：左标题 + 右上页码点
    ② 分隔线
    ③ 概览状态条（draw_chip：左标签 + 右信息）
    ④ 内容区
    ⑤ 页脚（分隔线 + 左说明 + 右时间）

顶部 100px 不归我们管：dash.sh 用 `eips -g img -y 100` 贴图，
Kindle 原生状态栏（左上角时间）得以保留、持续显示。
所以这里 H=1348（1448 - 100），坐标 0 对应屏幕 y=100。
"""

import os
from PIL import Image, ImageDraw, ImageFont

# PW3 屏幕参数：整屏 1072x1448，内容区扣掉顶部 100px 状态栏
SCREEN_W, SCREEN_H = 1072, 1448
TOP_BAR = 100
W, H = SCREEN_W, SCREEN_H - TOP_BAR
MARGIN = 58

# 电池图尺寸与贴图位置（右上角，不覆盖左上角原生时间）
STATUS_W, STATUS_H = 300, 100
STATUS_X, STATUS_Y = SCREEN_W - STATUS_W, 0

# ── 灰度层次 ──────────────────────────────
BG = 252          # 极浅米白底
INK = 24          # 主文字
INK_MID = 84      # 次级文字
INK_SOFT = 132    # 说明文字
TRACK = 229       # 进度条/时间轴轨道
FILL = 72         # 进度条填充
CHIP = 240        # 状态条底色
RULE = 222        # 分隔线
WHITE = 255       # 卡片底

# ── 字体 ─────────────────────────────────
_PINGFANG_CANDIDATES = [
    "/System/Library/AssetsV2/com_apple_MobileAsset_Font8/"
    "86ba2c91f017a3749571a82f2c6d890ac7ffb2fb.asset/AssetData/PingFang.ttc",
    "/System/Library/Fonts/PingFang.ttc",
]
# PingFang.ttc 的 face 索引（SC 变体）
_WEIGHT_INDEX = {
    "ultralight": 23, "thin": 19, "light": 15,
    "regular": 3, "medium": 7, "semibold": 11,
}
_FALLBACK = [
    ("/System/Library/Fonts/STHeiti Medium.ttc", 1),
    ("/System/Library/Fonts/STHeiti Light.ttc", 1),
    ("/System/Library/Fonts/Hiragino Sans GB.ttc", 2),
]

_font_file = None
for _p in _PINGFANG_CANDIDATES:
    if os.path.exists(_p):
        _font_file = _p
        break

_font_cache = {}


def load_font(size, weight="regular"):
    """按字重加载中文字体。

    weight: ultralight / thin / light / regular / medium / semibold
    在灰度墨水屏上相邻字重差异明显，正文用 light 可避免笔画糊在一起。
    """
    key = (size, weight)
    if key in _font_cache:
        return _font_cache[key]
    if _font_file:
        try:
            f = ImageFont.truetype(_font_file, size, index=_WEIGHT_INDEX.get(weight, 3))
            _font_cache[key] = f
            return f
        except Exception:
            pass
    for path, idx in _FALLBACK:
        try:
            f = ImageFont.truetype(path, size, index=idx)
            _font_cache[key] = f
            return f
        except Exception:
            continue
    return ImageFont.load_default()


def new_canvas():
    """浅米白底画布（内容区尺寸，不含顶部状态栏）。"""
    img = Image.new("L", (W, H), BG)
    return img, ImageDraw.Draw(img)


# ── 通用部件 ──────────────────────────────

def text_w(draw, text, font):
    return draw.textlength(text, font=font)


def draw_dots(draw, page, total=4, cy=None):
    """右上角页码点：当前页实心，其余空心。cy 为圆点垂直中心。"""
    r = 9
    gap = 30
    cy = cy if cy is not None else 44
    x0 = W - MARGIN - (total - 1) * gap - r * 2
    for i in range(1, total + 1):
        x = x0 + (i - 1) * gap
        if i == page:
            draw.ellipse([x, cy - r, x + r * 2, cy - r + r * 2], fill=INK)
        else:
            draw.ellipse([x, cy - r, x + r * 2, cy - r + r * 2], outline=INK_SOFT, width=3)


def draw_header(draw, title, page, total=4):
    """统一标题栏：左标题 + 右上页码点，下方分隔线。返回正文起始 y。

    四页都必须走这里，保证标题出现在完全相同的位置。
    """
    f_title = load_font(56, "semibold")
    y = 22
    draw.text((MARGIN, y), title, font=f_title, fill=INK)
    draw_dots(draw, page, total, cy=y + 34)
    y += 92
    draw.line([(MARGIN, y), (W - MARGIN, y)], fill=RULE, width=2)
    return y + 34


def draw_chip(draw, y, left_text, right_text, h=80):
    """浅灰圆角状态条（概览行）。返回下一行 y。

    右侧文本过长时自动省略：否则会反向压到左侧标签上（日程页「进行中 <标题>」
    最容易触发）。保留 24px 呼吸间距。
    """
    f = load_font(30, "regular")
    draw.rounded_rectangle([MARGIN, y, W - MARGIN, y + h], radius=16, fill=CHIP)
    draw.text((MARGIN + 28, y + (h - 36) // 2), left_text, font=f, fill=INK_SOFT)
    max_w = (W - MARGIN - 28) - (MARGIN + 28 + text_w(draw, left_text, f)) - 24
    if text_w(draw, right_text, f) > max_w:
        while right_text and text_w(draw, right_text + "…", f) > max_w:
            right_text = right_text[:-1]
        right_text += "…"
    w = text_w(draw, right_text, f)
    draw.text((W - MARGIN - 28 - w, y + (h - 36) // 2), right_text, font=f, fill=INK_MID)
    return y + h


def section_header(draw, y, name, sub="", f_name=None, f_sub=None):
    """分组标题：左分类名（半粗），右灰色副标题（右对齐）。返回下一行 y。"""
    f_name = f_name or load_font(44, "semibold")
    f_sub = f_sub or load_font(30, "regular")
    draw.text((MARGIN, y), name, font=f_name, fill=INK)
    if sub:
        w = text_w(draw, sub, f_sub)
        draw.text((W - MARGIN - w, y + 12), sub, font=f_sub, fill=INK_SOFT)
    return y + 92


def metric_row(draw, y, label, value, f_label=None, f_value=None):
    """明细行：左灰标签（基线对齐），右侧大号数值。返回下一行 y。"""
    f_label = f_label or load_font(34, "regular")
    f_value = f_value or load_font(70, "semibold")
    draw.text((MARGIN, y + 14), label, font=f_label, fill=INK_MID)
    w = text_w(draw, value, f_value)
    draw.text((W - MARGIN - w, y - 12), value, font=f_value, fill=INK)
    return y + 104


def draw_bar(draw, x, y, w, h, pct, radius=None):
    """圆角进度条：浅灰轨道 + 深灰填充。pct 为 0~100。"""
    r = h // 2 if radius is None else radius
    draw.rounded_rectangle([x, y, x + w, y + h], radius=r, fill=TRACK)
    pct = max(0, min(100, pct))
    fill_w = int(w * pct / 100)
    if fill_w >= h:
        draw.rounded_rectangle([x, y, x + fill_w, y + h], radius=r, fill=FILL)
    elif fill_w > 0:
        draw.rounded_rectangle([x, y, x + h, y + h], radius=r, fill=FILL)


def bar_caption(draw, y, text, font=None):
    """进度条右下角说明文字（重置时间等）。"""
    font = font or load_font(28, "regular")
    w = text_w(draw, text, font)
    draw.text((W - MARGIN - w, y), text, font=font, fill=INK_SOFT)


def divider(draw, y, gap=44):
    """细分隔线。返回下一行 y。"""
    draw.line([(MARGIN, y), (W - MARGIN, y)], fill=RULE, width=2)
    return y + gap


def footer(draw, left_text, right_text=""):
    """页脚：左说明 + 右时间戳，四页统一贴底。"""
    f = load_font(28, "regular")
    fy = H - 78
    draw.line([(MARGIN, fy), (W - MARGIN, fy)], fill=RULE, width=2)
    draw.text((MARGIN, fy + 22), left_text, font=f, fill=INK_SOFT)
    if right_text:
        w = text_w(draw, right_text, f)
        draw.text((W - MARGIN - w, fy + 22), right_text, font=f, fill=INK_SOFT)


def fit(draw, text, font, max_w):
    """按宽度截断并加省略号。"""
    if draw.textlength(text, font=font) <= max_w:
        return text
    while text and draw.textlength(text + "…", font=font) > max_w:
        text = text[:-1]
    return text + "…"
