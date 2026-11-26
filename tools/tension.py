"""
CoreBall - 张力分配计算器（纯 Python，不需要 Blender）

用法：
  python tension.py                 # 算当前默认位置
  python tension.py -430 330 1160   # 算指定位置

输出：四根线的目标张力，以及这个点是否力封闭。

原理（一句话）：
  4 根线只有 3 个平衡方程，所以有 1 个自由度。
  这个自由度由一个"零空间向量" n 表示：沿 n 加减，
  球的合力完全不变，但四根线的内部张力会整体上浮或下沉。
  我们用它把"最松的那根"顶到最小张力以上。
"""

import sys
import math

# ---------------- 几何 ----------------
# 八个墙锚（出线滑轮中心，墙平面；2026-11-24 墙平面出线）
ANCHORS = [
    (-760.0,   12.0, 1849.0),
    ( 780.0, 1100.0, 1760.0),
    (-300.0,   12.0, 1849.0),
    (-780.0, 1100.0, 1760.0),
]

# 另外 4 个墙锚（前角覆盖优化）：后右、左中、右中两处
EXTRA_ANCHORS = [
    ( 760.0,   12.0, 1670.0),
    (-808.0,  200.0, 1849.0),
    ( 808.0,  500.0, 1760.0),
    ( 808.0,  800.0, 1760.0),
]
ALL_ANCHORS = ANCHORS + EXTRA_ANCHORS

BALL_MASS   = 0.50      # 唯一口径：球 0.26 + 吊点 0.24（2026-11-23 定，见 docs/03）
G           = 9.81
TETHER_UP   = 0.60      # 供电张紧器给吊点的向上力，N（两股合计）
T_MIN       = 0.30      # 低于这个就认为线要松了，N
T_MAX       = 20.0      # 电机扭矩上限换算过来的最大张力，N


# ---------------- 向量小工具 ----------------
def sub(a, b):  return (a[0]-b[0], a[1]-b[1], a[2]-b[2])
def dot(a, b):  return a[0]*b[0] + a[1]*b[1] + a[2]*b[2]
def norm(a):    return math.sqrt(dot(a, a))
def unit(a):
    n = norm(a)
    return (a[0]/n, a[1]/n, a[2]/n)
def cross(a, b):
    return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])
def det3(a, b, c):
    return dot(a, cross(b, c))


def inv3(m):
    """3x3 矩阵求逆"""
    a, b, c = m
    d = det3(a, b, c)
    if abs(d) < 1e-12:
        raise ValueError("矩阵奇异：四根线共面或退化")
    # 伴随矩阵 / 行列式
    r0 = cross(b, c)
    r1 = cross(c, a)
    r2 = cross(a, b)
    return [
        (r0[0]/d, r0[1]/d, r0[2]/d),
        (r1[0]/d, r1[1]/d, r1[2]/d),
        (r2[0]/d, r2[1]/d, r2[2]/d),
    ]


# ---------------- 主计算 ----------------
def solve_subset(point, idx, anchors=None, W=None):
    """给定 4 个锚点索引，解最小范数特解 + 零空间 max-min。

    W 是希望四根绳提供的合力（N）；缺省为重力减供电上拉力。
    """
    anchors = anchors if anchors is not None else ANCHORS
    P = tuple(point)
    if W is None:
        W = (0.0, 0.0, BALL_MASS * G - TETHER_UP)

    u = []
    lengths = []
    for i in idx:
        d = sub(anchors[i], P)
        lengths.append(norm(d))
        u.append(unit(d))
    row = []
    for k in range(3):
        row.append([u[j][k] for j in range(4)])
    AAT = [[sum(row[i][m] * row[j][m] for m in range(4)) for j in range(3)]
           for i in range(3)]
    inv = inv3(AAT)
    tmp = [sum(inv[i][j] * W[j] for j in range(3)) for i in range(3)]
    Tp = [sum(u[i][k] * tmp[k] for k in range(3)) for i in range(4)]

    n = [
        det3(u[1], u[2], u[3]),
        -det3(u[0], u[2], u[3]),
        det3(u[0], u[1], u[3]),
        -det3(u[0], u[1], u[2]),
    ]

    cand = [0.0]
    for i in range(4):
        for j in range(i + 1, 4):
            dn = n[i] - n[j]
            if abs(dn) > 1e-9:
                cand.append((Tp[j] - Tp[i]) / dn)

    best_lam, best_min = 0.0, -1e18
    for lam in cand:
        m = min(Tp[i] + lam * n[i] for i in range(4))
        if m > best_min:
            best_min, best_lam = m, lam

    T = [Tp[i] + best_lam * n[i] for i in range(4)]
    margin = min(T)
    return {
        "idx": list(idx),
        "lengths": lengths,
        "u": u,
        "Tp": Tp,
        "n": n,
        "closed": margin >= T_MIN,
        "lam": best_lam,
        "margin": margin,
        "T": T,
        "W": W,
    }


HUB_GAP     = 160.0     # 球心 → 吊点，运行时按吊点解算（docs/03）


def solve(point):
    """固定四角锚点（旧基线，仅留作对比；运行时用 solve_selected）。"""
    return solve_subset(point, [0, 1, 2, 3], ANCHORS)


def _combos4(n):
    return [(a, b, c, d)
            for a in range(n - 3) for b in range(a + 1, n - 2)
            for c in range(b + 1, n - 1) for d in range(c + 1, n)]


SUBSETS4 = _combos4(len(ALL_ANCHORS))


def solve_force(point, W, idx=None, anchors=None):
    """指定支撑组，解出提供合力 W 的四根张力。"""
    idx = [0, 1, 2, 3] if idx is None else list(idx)
    anchors = anchors if anchors is not None else ANCHORS
    return solve_subset(point, idx, anchors, W=W)


def solve_selected(point, W=None):
    """8 选 4：四根都绷得住、余量最大；其余 4 根当闲散绳。"""
    best = fallback = None
    for idx in SUBSETS4:
        r = solve_subset(point, idx, ALL_ANCHORS, W=W)
        if max(r["T"]) > T_MAX:
            continue
        if r["margin"] >= T_MIN:
            score = r["margin"] - 0.005 * sum(r["T"])
            if best is None or score > best["score"]:
                best = dict(r, score=score)
        if fallback is None or r["margin"] > fallback["margin"]:
            fallback = r
    r = best or fallback
    r["support"] = list(r["idx"])
    r["idle"] = [i for i in range(len(ALL_ANCHORS)) if i not in r["support"]]
    r["support_names"] = ["A%d" % (i + 1) for i in r["support"]]
    r["idle_count"] = len(r["idle"])
    r["auto"] = True
    return r


def report(ball):
    """输入是**球心**（与 docs/03 默认位一致）；运行时按吊点（球心 +160）解算，
    输出机器实际选的 4 根支撑（8 选 4），不是旧基线的固定四角。"""
    hub = (ball[0], ball[1], ball[2] + HUB_GAP)
    r = solve_selected(hub)
    print("=" * 62)
    print("球心 P = (%.0f, %.0f, %.0f)   吊点 H = (%.0f, %.0f, %.0f)"
          % (ball + hub))
    print("需要线提供的合力 W = (%.2f, %.2f, %.2f) N" % r["W"])
    print("支撑（8 选 4）：%s · 闲散 %d 根"
          % (" ".join(r["support_names"]), r["idle_count"]))
    print("-" * 62)
    print("线长 / 张力：")
    for name, L, Tv in zip(r["support_names"], r["lengths"], r["T"]):
        print("  %s  L=%6.0f mm   T=%6.2f N" % (name, L, Tv))
    print("-" * 62)
    if not r["closed"]:
        print("  ! 最松的一根只有 %.2f N（目标 %.2f），余量不足" % (r["margin"], T_MIN))
        print("    物理上到得了，但被扰动一下某根线就会松 —— 行为层应避开这类位置")
    else:
        print("  OK 最松的一根 %.2f N，余量够" % r["margin"])
    zsum = sum(r["T"][i] * r["u"][i][2] for i in range(4))
    print("  合力校验：Σ T·u_z = %.2f N（应为 %.2f）" % (zsum, r["W"][2]))
    loosest = min(range(4), key=lambda i: r["T"][i])
    print("  最松：%s %.2f N" % (r["support_names"][loosest], r["T"][loosest]))
    tightest = max(range(4), key=lambda i: r["T"][i])
    print("  最紧：%s %.2f N" % (r["support_names"][tightest], r["T"][tightest]))
    if r["T"][tightest] > T_MAX:
        print("  ! 超过电机上限 %.0f N" % T_MAX)
    print("=" * 62)


if __name__ == "__main__":
    if len(sys.argv) >= 4:
        p = (float(sys.argv[1]), float(sys.argv[2]), float(sys.argv[3]))
        report(p)
    else:
        for p in [(-380, 520, 1300), (380, 520, 1300), (0, 520, 1300), (-380, 700, 1450)]:
            report(p)
