"""动态仿真的回归测试；直接运行，打印 PASS。"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dyn_params as P  # noqa: E402
import dyn_model as M  # noqa: E402
from tension import ALL_ANCHORS  # noqa: E402


def close(a, b, tol=1e-9, msg=""):
    if abs(a - b) > tol:
        raise SystemExit("FAIL: %s (%r != %r)" % (msg, a, b))


# ---------- 参数 ----------
close(len(P.ANCHORS), 8, msg="8 个锚点")
close(P.ANCHORS[0][0], -0.760, 1e-12, "A1 x")
close(P.P0[2] + P.P["ball_offset"], 1.460, 1e-12, "默认吊点 z")
if P.SUPPORT_P0 != (1, 2, 3, 5):
    raise SystemExit("FAIL: P0 支撑 %r" % (P.SUPPORT_P0,))

# ---------- 四元数 ----------
R = M.quat_to_R(np.array([1.0, 0, 0, 0]))
close(np.linalg.norm(R - np.eye(3)), 0.0, 1e-12, "单位四元数")
q = M.quat_normalize(np.array([0.0, 0, 0, 1.0]))
R = M.quat_to_R(q)
close(R[0, 0], -1.0, 1e-9, "绕 z 转 180°")

# ---------- point 模式静态平衡 ----------
plant = M.Plant(attachment="point")
for _ in range(5000):
    plant.step(plant.current)
drift = np.linalg.norm(plant.ball_center() - np.array(P.P0))
if drift > 1e-4:
    raise SystemExit("FAIL: point 平衡漂移 %.6f m" % drift)

W = np.array([0.0, 0.0, P.P["m"] * P.G - P.P["tether_up"]])
if np.linalg.norm(plant.cable_force() - W) > 1e-5:
    raise SystemExit("FAIL: 缆绳合力 %r != %r" % (plant.cable_force(), W))

# ---------- 绳长变化率符号 ----------
plant = M.Plant(attachment="point")
i = plant.support[0]
a = np.array(ALL_ANCHORS[i]) * P.MM
p = plant.attachment_points()[i]
u = (a - p) / np.linalg.norm(a - p)
plant.v = u * 0.01
if not plant.cable_rates()[i] < 0:
    raise SystemExit("FAIL: 朝锚点移动时 Ldot 应为负")

# ---------- 只拉不推 ----------
plant = M.Plant(attachment="point")
plant.L0 = plant.cable_lengths() + 0.001
if np.any(plant.tensions() != 0):
    raise SystemExit("FAIL: 松弛绳不应有张力")

# ---------- 环形挂点有力矩 ----------
plant = M.Plant(attachment="ring")
if np.linalg.norm(plant.net_torque()) < 1e-3:
    raise SystemExit("FAIL: 环形挂点应产生静态力矩")

print("PASS")
