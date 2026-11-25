"""把 tools/tension.py 里的唯一口径导出成 web/params.json。

网页（command.html / control.html）启动时 fetch 这个文件覆盖内置默认值；
文件不存在时用内置默认值，行为与旧版一致。

改了 tension.py 的锚点 / 质量 / 张力阈值后跑一次：

  python tools/export_params.py

tools/test_params.py 会锁住 params.json 与 tension.py 的一致性。
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
ROOT = os.path.dirname(HERE)

import tension as T  # noqa: E402

# 与 blender/cmd_runtime.py、web/command.html 保持同一组数
PARAMS = {
    "version": 1,
    "anchors": [list(a) for a in T.ALL_ANCHORS],
    "mass_kg": T.BALL_MASS,
    "tether_up": T.TETHER_UP,
    "t_min": T.T_MIN,
    "t_max": T.T_MAX,
    "hub_gap": 160.0,          # 球心 → 吊点
    "vmax": 356.0,             # mm/s，S 曲线峰值速度
    "rebound": 4.0,            # 落定越冲 mm
    "settle": 0.4,             # 越冲持续 s
    "neck": {"x": 0.0, "y": 890.0, "r": 210.0},
    "booth": {"hx": 820.0, "y0": 0.0, "y1": 1100.0, "y0p": 250.0,
              "ball_r": 40.0, "gap": 5.0},
    "default_ball": [-380.0, 520.0, 1300.0],
}


def export(path=None):
    p = path or os.path.join(ROOT, "web", "params.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(PARAMS, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return p


if __name__ == "__main__":
    print("已写出", export())
