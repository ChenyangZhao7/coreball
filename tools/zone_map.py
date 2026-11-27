"""
CoreBall - 允许飞行区地图

把三件事叠在一起：
  1. 张力余量（tension.py 算）
  2. 脖子禁区
  3. 挡不挡显示器

输出：out/rig/zone_map.html，三个高度各一张俯视图。

用法：
  python zone_map.py
"""

import os
import math
import tension as T

# ---------------- 参数 ----------------
EYE      = (0.0, 890.0, 1250.0)
NECK     = (0.0, 890.0, 1180.0)
R_HARD   = 250.0   # 球心硬约束：r210 圆柱 + 球半径 40
R_SOFT   = 305.0
MON_HALF_X = 340.0       # 显示器宽度一半 + 余量
MON_TOP_Z  = 1150.0

X_MIN, X_MAX, NX = -790.0, 790.0, 32
Y_MIN, Y_MAX, NY = 40.0, 1060.0, 21
Z_LEVELS = [1100.0, 1250.0, 1400.0]

MARGIN_MIN = 0.30
CELL = 22
PAD = 46

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "blender", "out", "rig", "zone_map.html")


def classify(x, y, z):
    """返回 (状态, 余量)"""
    d = math.hypot(x - NECK[0], y - NECK[1])
    margin = T.solve((x, y, z + 60.0))["margin"]     # +60 = 吊点高于球心

    if d < R_HARD:
        return "hard", margin
    if z < MON_TOP_Z and abs(x) < MON_HALF_X and y < EYE[1]:
        return "screen", margin
    if d < R_SOFT:
        return "soft", margin
    if margin < MARGIN_MIN:
        return "weak", margin
    return "good", margin


COLORS = {
    "hard":   "#6b2226",
    "screen": "#2a3540",
    "soft":   "#7a5220",
    "weak":   "#8a6a24",
    "good":   None,
}


def good_color(m):
    """余量越大越绿"""
    t = max(0.0, min(1.0, (m - MARGIN_MIN) / 0.7))
    r = int(30 + (110 - 30) * (1 - t))
    g = int(120 + (190 - 120) * t)
    b = int(105 + (150 - 105) * (1 - t))
    return "#%02x%02x%02x" % (r, g, b)


def build_panel(z):
    w = NX * CELL
    h = NY * CELL
    parts = []
    stats = {"good": 0, "weak": 0, "soft": 0, "screen": 0, "hard": 0, "total": 0}

    for j in range(NY):
        y = Y_MAX - (j + 0.5) * (Y_MAX - Y_MIN) / NY
        for i in range(NX):
            x = X_MIN + (i + 0.5) * (X_MAX - X_MIN) / NX
            state, m = classify(x, y, z)
            stats[state] += 1
            stats["total"] += 1
            col = COLORS[state] if COLORS[state] else good_color(m)
            op = 1.0 if state == "good" else 0.55
            parts.append(
                '<rect x="%d" y="%d" width="%d" height="%d" fill="%s" fill-opacity="%.2f"/>'
                % (i * CELL, j * CELL, CELL - 1, CELL - 1, col, op))

    # 人的位置
    px = PAD + (NECK[0] - X_MIN) / (X_MAX - X_MIN) * w
    py = PAD + (Y_MAX - NECK[1]) / (Y_MAX - Y_MIN) * h
    overlay = (
        '<circle cx="%.1f" cy="%.1f" r="%.1f" fill="none" stroke="#e08c88" '
        'stroke-width="1.4" stroke-dasharray="4 4"/>' % (px, py, R_SOFT / (X_MAX - X_MIN) * w)
    )

    usable = 100.0 * stats["good"] / stats["total"]
    svg = (
        '<svg viewBox="0 0 %d %d" xmlns="http://www.w3.org/2000/svg">'
        '<rect width="%d" height="%d" fill="#0c0f13"/>'
        '<g transform="translate(%d,%d)">%s%s</g>'
        '<text x="8" y="26" fill="#c2ccd6" font-size="14" font-weight="600">z = %d mm</text>'
        '<text x="8" y="%d" fill="#6f7a85" font-size="11">可用 %.0f%%</text>'
        '</svg>'
        % (w + PAD * 2, h + PAD * 2 + 8, w + PAD * 2, h + PAD * 2 + 8,
           PAD, PAD + 8, "".join(parts), overlay,
           int(z), h + PAD + 26, usable)
    )
    return svg, stats


def main():
    panels = []
    summary = []
    for z in Z_LEVELS:
        svg, st = build_panel(z)
        panels.append(svg)
        good = 100.0 * st["good"] / st["total"]
        weak = 100.0 * st["weak"] / st["total"]
        blocked = 100.0 * (st["screen"] + st["soft"] + st["hard"]) / st["total"]
        summary.append((z, good, weak, blocked))

    html = """<!doctype html><html lang="zh"><head><meta charset="utf-8">
<title>允许飞行区</title><style>
:root{color-scheme:dark}
body{margin:0;padding:36px 24px 70px;background:#0a0d10;color:#d7dbe0;
font:15px/1.65 "Segoe UI","Microsoft YaHei",system-ui,sans-serif}
.wrap{max-width:760px;margin:0 auto}
h1{font-size:21px;margin:0 0 4px}
.sub{color:#79838d;font-size:13px}
svg{display:block;width:100%%;height:auto;margin-top:14px;border-radius:12px}
table{border-collapse:collapse;margin-top:20px;font-size:13.5px}
th,td{text-align:left;padding:8px 22px 8px 0;border-bottom:1px solid #1d232a}
th{color:#8b949e;font-weight:500}
.legend{display:flex;gap:18px;margin-top:14px;font-size:12.5px;color:#98a3ad;flex-wrap:wrap}
.dot{display:inline-block;width:11px;height:11px;border-radius:3px;margin-right:6px;vertical-align:-1px}
</style></head><body><div class="wrap">
<h1>允许飞行区</h1>
<div class="sub">张力余量 &ge; 0.30 N ｜ 避开脖子圆柱 ｜ 不挡显示器</div>
<div class="legend">
<span><i class="dot" style="background:#3f8f6a"></i>可用</span>
<span><i class="dot" style="background:#8a6a24"></i>余量不足</span>
<span><i class="dot" style="background:#7a5220"></i>软禁区</span>
<span><i class="dot" style="background:#2a3540"></i>挡屏幕</span>
<span><i class="dot" style="background:#6b2226"></i>硬禁区</span>
</div>
%s
<table><tr><th>高度</th><th>可用</th><th>余量不足</th><th>被禁</th></tr>%s</table>
</div></body></html>""" % (
        "".join(panels),
        "".join("<tr><td>z = %d</td><td>%.0f%%</td><td>%.0f%%</td><td>%.0f%%</td></tr>"
                % (z, g, w, b) for z, g, w, b in summary))

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)

    print("=" * 52)
    for z, g, w, b in summary:
        print("z=%4d   可用 %3.0f%%   余量不足 %3.0f%%   被禁 %3.0f%%" % (z, g, w, b))
    print("输出:", os.path.abspath(OUT))
    print("=" * 52)


if __name__ == "__main__":
    main()
