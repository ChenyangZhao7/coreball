"""覆盖率的回归测试：锁定墙平面出线后的绿/黄/红比例。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import coverage as C


def close(a, b):
    return abs(a - b) < 0.3


r = C.report()
assert close(r["hub_full"], 100.0), r
assert close(r["hub_practical"], 100.0), r
assert close(r["ball_full"], 99.6), r
assert close(r["ball_practical"], 100.0), r
assert close(r["hub_green"], 85.8), r
assert close(r["hub_yellow"], 14.2), r
assert close(r["hub_red"], 0.0), r
assert close(r["hub_green"] + r["hub_yellow"] + r["hub_red"], 100.0), r

print("PASS")
