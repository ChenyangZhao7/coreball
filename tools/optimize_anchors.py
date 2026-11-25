"""Search wall-only 8-anchor layouts for reachable workspace.

Target space:
  - above the desk: z >= 900
  - inside the three walls (ball center): |x| <= 775, 45 <= y <= 1055
  - not touching the neck cylinder: r >= 250 around (0, 890)
  - not behind the person: exclude y > 900 with |x| < 350
  - z <= 1500

Anchors are the sheave exit points on the three walls:
  back wall  y = 12, x in [-760, 760]
  left wall  x = -808, y in [150, 950]
  right wall x =  808, y in [150, 950]
  sheave exit z = 1670 / 1760 / 1849

Usage:
  python tools/optimize_anchors.py [--sets 60] [--seed 7]
"""
import argparse
import math
import random
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tension as T

BACK_X = [-760, -550, -300, 0, 300, 550, 760]
SIDE_Y = [200, 400, 600, 800, 950, 1100]
Z_CHOICES = [1670, 1760, 1849]
SUBSETS = T.SUBSETS4

TARGET = []
for x in (-675, -525, -375, -225, -75, 75, 225, 375, 525, 675):
    for y in (150, 300, 450, 600, 750, 900, 1050):
        if y > 900 and abs(x) < 350:
            continue
        if math.hypot(x, y - 890) < 250:
            continue
        for z in (900, 1100, 1300, 1500):
            TARGET.append((x, y, z))


def best_for(point, anchors):
    best = fallback = None
    for idx in SUBSETS:
        r = T.solve_subset(point, idx, anchors)
        if max(r["T"]) > T.T_MAX:
            continue
        if r["margin"] >= T.T_MIN:
            score = r["margin"] - 0.005 * sum(r["T"])
            if best is None or score > best["score"]:
                best = dict(r, score=score)
        if fallback is None or r["margin"] > fallback["margin"]:
            fallback = r
    return best or fallback


def coverage(anchors):
    ok = 0
    for p in TARGET:
        r = best_for(p, anchors)
        if r and r["closed"]:
            ok += 1
    return ok / len(TARGET)


def spaced(vals, gap=180):
    return all(abs(a - b) >= gap for i, a in enumerate(vals)
               for b in vals[i + 1:])


def random_layout(rng):
    while True:
        back = sorted(rng.sample(BACK_X, 3))
        left = sorted(rng.sample(SIDE_Y, 2))
        right = sorted(rng.sample(SIDE_Y, 3))
        if spaced(back) and spaced(left) and spaced(right):
            break
    anchors = ([(x, 12.0, rng.choice(Z_CHOICES)) for x in back]
               + [(-808.0, y, rng.choice(Z_CHOICES)) for y in left]
               + [(808.0, y, rng.choice(Z_CHOICES)) for y in right])
    return anchors


def current_layout():
    return [
        (-760.0, 12.0, 1849.0), (780.0, 1100.0, 1760.0),
        (-300.0, 12.0, 1849.0), (-780.0, 1100.0, 1760.0),
        (760.0, 12.0, 1670.0), (-808.0, 200.0, 1849.0),
        (808.0, 500.0, 1760.0), (808.0, 800.0, 1760.0),
    ]


def label(anchors):
    back = sorted(a[0] for a in anchors if abs(a[1] - 12.0) < 5)
    left = sorted(a[1] for a in anchors if abs(a[0] + 808.0) < 5)
    right = sorted(a[1] for a in anchors if abs(a[0] - 808.0) < 5)
    return "back x=%s  left y=%s  right y=%s" % (back, left, right)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sets", type=int, default=60)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    rng = random.Random(a.seed)

    print("target points:", len(TARGET))
    cur = current_layout()
    print("current:", label(cur), "coverage %.1f%%" % (coverage(cur) * 100))

    best = None
    for i in range(a.sets):
        anchors = random_layout(rng)
        c = coverage(anchors)
        if best is None or c > best[0]:
            best = (c, anchors)
            print("  set %2d: %.1f%%  %s" % (i, c * 100, label(anchors)), flush=True)

    c, anchors = best
    print("")
    print("BEST coverage %.1f%%" % (c * 100))
    print(label(anchors))
    for p in anchors:
        print("  (%.0f, %.0f, %.0f)" % p)
    for z in (900, 1100, 1300, 1500):
        pts = [p for p in TARGET if p[2] == z]
        ok = sum(1 for p in pts if (lambda r: r and r["closed"])(best_for(p, anchors)))
        print("  z=%4d: %3d/%3d" % (z, ok, len(pts)))


if __name__ == "__main__":
    main()
