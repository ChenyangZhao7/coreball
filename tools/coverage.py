"""覆盖率报告：墙平面 8 锚 + 8 选 4，按绿/黄/红统计。

单位 mm / N。运行口径：
  ball = 球心（3D 指挥页）
  hub  = 吊点 = 球心 + 160（Blender 运行时）
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import tension as T
import optimize_anchors as O


def _best_for(p, anchors):
    combos = T._combos4(len(anchors))
    best = fallback = None
    for idx in combos:
        try:
            r = T.solve_subset(p, idx, anchors)
        except Exception:
            continue
        if max(r["T"]) > T.T_MAX:
            continue
        if r["margin"] >= T.T_MIN:
            score = r["margin"] - 0.005 * sum(r["T"])
            if best is None or score > best["score"]:
                best = dict(r, score=score)
        if fallback is None or r["margin"] > fallback["margin"]:
            fallback = r
    return best or fallback


def _counts(dz):
    total = practical = 0
    closed = closed_practical = 0
    color = {"green": 0, "yellow": 0, "red": 0}
    for ball in O.TARGET:
        r = _best_for((ball[0], ball[1], ball[2] + dz), T.ALL_ANCHORS)
        m = r["margin"] if r else float("-inf")
        total += 1
        if m >= 1.0:
            color["green"] += 1
        elif m >= T.T_MIN:
            color["yellow"] += 1
        else:
            color["red"] += 1
        if m >= T.T_MIN:
            closed += 1
        if 300 <= ball[1] <= 900:
            practical += 1
            if m >= T.T_MIN:
                closed_practical += 1
    pct = lambda a, b: 100.0 * a / b if b else 0.0
    return {
        "total": total,
        "practical": practical,
        "closed": closed,
        "closed_practical": closed_practical,
        "green": pct(color["green"], total),
        "yellow": pct(color["yellow"], total),
        "red": pct(color["red"], total),
    }


def report():
    ball = _counts(0.0)
    hub = _counts(160.0)
    pct = lambda a, b: 100.0 * a / b if b else 0.0
    return {
        "ball_full": pct(ball["closed"], ball["total"]),
        "ball_practical": pct(ball["closed_practical"], ball["practical"]),
        "hub_full": pct(hub["closed"], hub["total"]),
        "hub_practical": pct(hub["closed_practical"], hub["practical"]),
        "hub_green": hub["green"],
        "hub_yellow": hub["yellow"],
        "hub_red": hub["red"],
    }


if __name__ == "__main__":
    r = report()
    print("全空间（吊点） %.1f%%   实用区 %.1f%%" % (r["hub_full"], r["hub_practical"]))
    print("全空间（球心） %.1f%%   实用区 %.1f%%" % (r["ball_full"], r["ball_practical"]))
    print("吊点 绿 %.1f%% / 黄 %.1f%% / 红 %.1f%%" %
          (r["hub_green"], r["hub_yellow"], r["hub_red"]))
