"""锁住 web/params.json 与 tools/tension.py 的一致：漂移了就跑 export_params.py。"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
ROOT = os.path.dirname(HERE)

import tension as T  # noqa: E402
import export_params as E  # noqa: E402


def eq(a, b, msg):
    if a != b:
        raise SystemExit("FAIL: %s（%r != %r）—— 重跑 python tools/export_params.py"
                         % (msg, a, b))


path = os.path.join(ROOT, "web", "params.json")
with open(path, "r", encoding="utf-8") as f:
    p = json.load(f)

eq(p["anchors"], [list(a) for a in T.ALL_ANCHORS], "锚点")
eq(p["mass_kg"], T.BALL_MASS, "质量口径")
eq(p["t_min"], T.T_MIN, "张力下限")
eq(p["t_max"], T.T_MAX, "电机上限")
eq(p["tether_up"], T.TETHER_UP, "供电线上拉力")
eq(p, E.PARAMS, "导出内容（重跑 export_params.py）")

print("PASS")
