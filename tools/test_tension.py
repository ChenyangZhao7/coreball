"""tension.py 的数学性质测试：力平衡、零空间、max-min 最优性。

coverage.py 锁的是覆盖率结论；这里锁的是解法本身。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tension as T  # noqa: E402

HUB = (-380.0, 520.0, 1300.0 + T.HUB_GAP)


def eq(a, b, msg, tol=1e-9):
    if abs(a - b) > tol:
        raise SystemExit("FAIL: %s (%r != %r)" % (msg, a, b))


# ---------- 默认位锁定（docs/03、docs/08 的数字） ----------
r = T.solve_selected(HUB)
if r["support_names"] != ["A2", "A3", "A4", "A6"]:
    raise SystemExit("FAIL: 默认支撑 %r" % r["support_names"])
for got, want in zip(r["T"], [2.775, 2.338, 2.315, 2.315]):
    eq(got, want, "默认位张力", 0.01)
eq(r["margin"], min(r["T"]), "margin 就是四根里的最小值")

# ---------- 力平衡：Σ T·u = W ----------
for p in [HUB, (0.0, 700.0, 1460.0), (-700.0, 300.0, 1310.0), (600.0, 900.0, 1100.0)]:
    r = T.solve_selected(p)
    for k in range(3):
        s = sum(r["T"][i] * r["u"][i][k] for i in range(4))
        eq(s, r["W"][k], "力平衡 %s 轴 %s" % ("xyz"[k], p), 1e-6)
    if r["closed"]:
        if max(r["T"]) > T.T_MAX + 1e-9:
            raise SystemExit("FAIL: 闭合却超电机上限 %s" % (p,))

# ---------- 零空间：沿 n 走，合力不变 ----------
r = T.solve_subset(HUB, [1, 2, 3, 5], T.ALL_ANCHORS)
for k in range(3):
    s = sum(r["n"][i] * r["u"][i][k] for i in range(4))
    eq(s, 0.0, "零空间方向不产生合力（%s 轴）" % "xyz"[k], 1e-9)

# ---------- max-min 最优性：解附近暴力扫 λ，没人更大 ----------
best = r["margin"]
lo, hi = r["lam"] - 2.0, r["lam"] + 2.0
for i in range(801):
    lam = lo + (hi - lo) * i / 800
    m = min(r["Tp"][j] + lam * r["n"][j] for j in range(4))
    if m > best + 1e-6:
        raise SystemExit("FAIL: λ=%.4f 给出更大的最松张力 %.4f > %.4f" % (lam, m, best))

# ---------- 8 选 4 不漏解：闭合组合里分数最高的就是被选中的 ----------
r = T.solve_selected(HUB)
for idx in T.SUBSETS4:
    try:
        s = T.solve_subset(HUB, idx, T.ALL_ANCHORS)
    except ValueError:
        continue
    if max(s["T"]) > T.T_MAX or s["margin"] < T.T_MIN:
        continue
    score = s["margin"] - 0.005 * sum(s["T"])
    if score > r["score"] + 1e-9:
        raise SystemExit("FAIL: 组合 %r 分数更高却没被选中" % (idx,))

# ---------- 任意期望力：Σ T·u = W ----------
W = (0.25, -0.40, 4.20)
r = T.solve_force(HUB, W, [1, 2, 3, 5], T.ALL_ANCHORS)
for k in range(3):
    s = sum(r["T"][i] * r["u"][i][k] for i in range(4))
    eq(s, W[k], "任意力平衡 %s" % "xyz"[k], 1e-9)

# ---------- 8 选 4 也接受任意力 ----------
r = T.solve_selected(HUB, (0.8, 0.0, 4.305))
for k in range(3):
    s = sum(r["T"][i] * r["u"][i][k] for i in range(4))
    eq(s, (0.8, 0.0, 4.305)[k], "选绳后力平衡 %s" % "xyz"[k], 1e-6)

# ---------- 缺省行为不变 ----------
a = T.solve_selected(HUB)
b = T.solve_selected(HUB, (0.0, 0.0, T.BALL_MASS * T.G - T.TETHER_UP))
eq(a["score"], b["score"], "缺省 W 与重力一致", 1e-12)

print("PASS")
