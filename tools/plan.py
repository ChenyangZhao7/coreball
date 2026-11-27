"""
CoreBall - 最小运动规划：在允许区里找路径

同一对起终点，三种代价权重 → 三条不同的路。
安全是硬约束（红区不可进），人格体现在代价函数里。

用法：
  python plan.py
"""

import os
import math
import heapq
import tension as T

# ---------------- 场地 ----------------
NECK   = (0.0, 890.0, 1180.0)
R_HARD = 250.0   # 球心硬约束：r210 圆柱 + 球半径 40
R_SOFT = 305.0
MON_HALF_X = 340.0
MON_TOP_Z  = 1150.0
MARGIN_MIN = 0.30

GRID = 40.0
X0, X1 = -780.0, 780.0
Y0, Y1 = 60.0, 1020.0
NZ = 1250.0

START = (-520.0, 700.0)      # 左手边
GOAL  = (520.0, 700.0)       # 右手边（要绕过人）

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "blender", "out", "rig", "plan.html")


def state_of(x, y):
    d = math.hypot(x - NECK[0], y - NECK[1])
    m = T.solve((x, y, NZ + 60.0))["margin"]
    if d < R_HARD:
        return "hard", m
    if NZ < MON_TOP_Z and abs(x) < MON_HALF_X and y < 890.0:
        return "screen", m
    if d < R_SOFT:
        return "soft", m
    return ("good" if m >= MARGIN_MIN else "weak"), m


# ---------------- 网格 ----------------
NX = int((X1 - X0) / GRID) + 1
NY = int((Y1 - Y0) / GRID) + 1

cells = {}
for j in range(NY):
    for i in range(NX):
        x, y = X0 + i * GRID, Y0 + j * GRID
        st, m = state_of(x, y)
        cells[(i, j)] = (st, m)

BLOCKED = {"hard", "screen"}   # 只有硬禁区真的进不去；软禁区是代价


def nearest_open(pt):
    """把请求点吸附到最近的可用格"""
    bi, bj, bd = 0, 0, 1e18
    for (i, j), (st, m) in cells.items():
        if st in BLOCKED:
            continue
        d = (X0 + i * GRID - pt[0]) ** 2 + (Y0 + j * GRID - pt[1]) ** 2
        if d < bd:
            bd, bi, bj = d, i, j
    return bi, bj


def allocost(i, j, mode):
    st, m = cells[(i, j)]
    if st in BLOCKED:
        return None
    x, y = X0 + i * GRID, Y0 + j * GRID
    d_person = math.hypot(x - NECK[0], y - NECK[1])

    c = 1.0
    if st == "soft":
        c += {"direct": 1.2, "steady": 9.0, "clingy": 0.15, "shy": 9.0}[mode]
    if st == "weak":
        c += {"direct": 1.0, "steady": 10.0, "clingy": 10.0, "shy": 10.0}[mode] * (MARGIN_MIN - m) / MARGIN_MIN * 2.0

    if mode == "steady":
        c += 4.0 * max(0.0, 0.6 - m) / 0.6
    if mode == "clingy":
        c -= 0.5 * max(0.0, 1.0 - d_person / 520.0)
    if mode == "shy":
        c += 3.5 * max(0.0, 1.0 - d_person / 780.0)
    return max(0.04, c)


def astar(start, goal, mode):
    si, sj = nearest_open(start)
    gi, gj = nearest_open(goal)
    openq = [(0.0, si, sj)]
    came = {(si, sj): None}
    gsc = {(si, sj): 0.0}
    while openq:
        _, i, j = heapq.heappop(openq)
        if (i, j) == (gi, gj):
            break
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                if di == 0 and dj == 0:
                    continue
                ni, nj = i + di, j + dj
                if (ni, nj) not in cells:
                    continue
                c = allocost(ni, nj, mode)
                if c is None:
                    continue
                step = math.hypot(di, dj) * c
                ng = gsc[(i, j)] + step
                if (ni, nj) not in gsc or ng < gsc[(ni, nj)] - 1e-9:
                    gsc[(ni, nj)] = ng
                    came[(ni, nj)] = (i, j)
                    h = math.hypot(ni - gi, nj - gj)
                    heapq.heappush(openq, (ng + h, ni, nj))
    if (gi, gj) not in came:
        return []
    path, cur = [], (gi, gj)
    while cur:
        path.append((X0 + cur[0] * GRID, Y0 + cur[1] * GRID))
        cur = came[cur]
    return path[::-1]


# ---------------- 画图 ----------------
CELL_PX = 15
PAD = 54

MODES = [
    ("direct", "#e0b060", "直给 · 只看距离"),
    ("steady", "#4fa87f", "稳 · 重罚低余量"),
    ("clingy", "#6aa8d8", "黏人 · 偏好靠近你"),
    ("shy", "#b06fa8", "怕人 · 躲得远远的"),
]

COL = {"hard": "#6b2226", "screen": "#232c36", "soft": "#6b4a20"}


def good_color(m):
    t = max(0.0, min(1.0, (m - MARGIN_MIN) / 0.7))
    r = int(26 + (70 - 26) * (1 - t))
    g = int(74 + (130 - 74) * t)
    b = int(64 + (105 - 64) * (1 - t))
    return "#%02x%02x%02x" % (r, g, b)


def px(x, y):
    return ((x - X0) / GRID * CELL_PX, (Y1 - y) / GRID * CELL_PX)


def main():
    paths = {m: astar(START, GOAL, m) for m, _, _ in MODES}

    w = NX * CELL_PX
    h = NY * CELL_PX
    rects = []
    for j in range(NY):
        for i in range(NX):
            st, m = cells[(i, j)]
            col = good_color(m) if st not in COL else COL[st]
            op = 1.0 if st not in ("hard", "screen", "soft") else 0.75
            rects.append('<rect x="%d" y="%d" width="%d" height="%d" fill="%s" fill-opacity="%.2f"/>'
                         % (i * CELL_PX, (NY - 1 - j) * CELL_PX,
                            CELL_PX - 1, CELL_PX - 1, col, op))

    lines = []
    for mode, colr, _ in MODES:
        pts = paths[mode]
        if not pts:
            continue
        d = " ".join("%.1f,%.1f" % px(x, y) for x, y in pts)
        lines.append('<polyline points="%s" fill="none" stroke="%s" stroke-width="2.4" '
                     'stroke-linejoin="round" stroke-linecap="round" opacity="0.95"/>' % (d, colr))

    sx, sy = px(*START)
    gx, gy = px(*GOAL)
    nx, ny = px(NECK[0], NECK[1])
    rad = R_SOFT / GRID * CELL_PX

    svg = ('<svg viewBox="0 0 %d %d" xmlns="http://www.w3.org/2000/svg">'
           '<rect width="%d" height="%d" fill="#0a0d10"/>'
           '<g transform="translate(%d,%d)">%s%s'
           '<circle cx="%.1f" cy="%.1f" r="%.1f" fill="none" stroke="#c96a66" '
           'stroke-width="1.6" stroke-dasharray="5 5"/>'
           '<circle cx="%.1f" cy="%.1f" r="7" fill="#cfe3f0"/>'
           '<circle cx="%.1f" cy="%.1f" r="7" fill="#f0d9a8"/>'
           '<text x="%.1f" y="%.1f" fill="#9aa6b0" font-size="11">待命</text>'
           '<text x="%.1f" y="%.1f" fill="#c8b483" font-size="11">手边</text>'
           '</g></svg>'
           % (w + PAD * 2, h + PAD * 2, w + PAD * 2, h + PAD * 2,
              PAD, PAD, "".join(rects), "".join(lines),
              nx, ny, rad,
              sx, sy, gx, gy,
              sx - 34, sy - 12, gx - 20, gy - 14))

    legend = "".join('<span><i style="background:%s"></i>%s</span>' % (c, n)
                     for _, c, n in MODES)

    stats = []
    for mode, _, name in MODES:
        pts = paths[mode]
        if not pts:
            stats.append("<tr><td>%s</td><td>找不到路径</td><td>—</td><td>—</td></tr>" % name)
            continue
        length = sum(math.hypot(pts[k + 1][0] - pts[k][0], pts[k + 1][1] - pts[k][1])
                     for k in range(len(pts) - 1))
        ms = [cells[((round((x - X0) / GRID)), (round((y - Y0) / GRID)))][1] for x, y in pts]
        stats.append("<tr><td>%s</td><td>%d mm</td><td>%.2f N</td><td>%d</td></tr>"
                     % (name, length, min(ms), len(pts)))

    html = """<!doctype html><html lang="zh"><head><meta charset="utf-8">
<title>路径与人格</title><style>
:root{color-scheme:dark}
body{margin:0;padding:36px 24px 70px;background:#0a0d10;color:#d7dbe0;
font:15px/1.65 "Segoe UI","Microsoft YaHei",system-ui,sans-serif}
.wrap{max-width:820px;margin:0 auto}
h1{font-size:21px;margin:0 0 4px}
.sub{color:#79838d;font-size:13px}
svg{display:block;width:100%%;height:auto;margin-top:16px;border-radius:12px}
table{border-collapse:collapse;margin-top:18px;font-size:13.5px;width:100%%}
th,td{text-align:left;padding:8px 20px 8px 0;border-bottom:1px solid #1d232a}
th{color:#8b949e;font-weight:500}
.legend{display:flex;gap:20px;margin-top:14px;font-size:13px;color:#98a3ad;flex-wrap:wrap}
.legend i{display:inline-block;width:16px;height:3px;border-radius:2px;margin-right:7px;vertical-align:3px}
</style></head><body><div class="wrap">
<h1>同一对起终点，三种走法</h1>
<div class="sub">红区是硬约束，谁都进不去。差别全在代价函数里。</div>
<div class="legend">%s</div>
%s
<table><tr><th>走法</th><th>路径长度</th><th>最小余量</th><th>拐点</th></tr>%s</table>
</div></body></html>""" % (legend, svg, "".join(stats))

    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    print("输出:", os.path.abspath(OUT))
    for mode, _, name in MODES:
        print("  %-24s %d 个点" % (name, len(paths[mode])))


if __name__ == "__main__":
    main()
