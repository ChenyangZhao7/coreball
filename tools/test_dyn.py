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
if np.linalg.norm(plant.cable_force() - W) > 5e-3:
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

# ---------- 电流夹紧 ----------
plant = M.Plant(attachment="point")
plant.step(np.full(8, 10.0), dt=P.P["dt"])
if np.max(np.abs(plant.current)) > P.P["i_max"] + 1e-9:
    raise SystemExit("FAIL: 电流没夹紧")

# ---------- 线速度夹紧 ----------
plant = M.Plant(attachment="point")
for _ in range(2000):
    plant.step(np.full(8, P.P["i_max"]), dt=P.P["dt"])
vmax = P.P["v_line_max"] / P.P["drum_r"]
if np.max(np.abs(plant.theta_dot)) > vmax + 1e-6:
    raise SystemExit("FAIL: 卷筒线速度没夹紧")

# ---------- 通电前馈保持平衡 ----------
plant = M.Plant(attachment="point")
ff = plant.current.copy()
for _ in range(5000):
    plant.step(ff, dt=P.P["dt"])
drift = np.linalg.norm(plant.ball_center() - np.array(P.P0))
if drift > 1e-4:
    raise SystemExit("FAIL: 绞盘平衡漂移 %.6f m" % drift)

# ---------- 收绳让张力上升 ----------
plant = M.Plant(attachment="point")
i = plant.support[0]
t0 = plant.tensions()[i]
cmd = plant.current.copy()
cmd[i] = min(P.P["i_max"], cmd[i] + 0.02)
plant.step(cmd, dt=P.P["dt"])
if not plant.tensions()[i] > t0:
    raise SystemExit("FAIL: 收绳应让张力上升")

import dyn_control as C  # noqa: E402

# ---------- 轨迹端点 ----------
s, sd, sa = C.min_jerk(0.0, 1.0)
close(s, 0.0, 1e-12, "min_jerk 起点")
s, sd, sa = C.min_jerk(1.0, 1.0)
close(s, 1.0, 1e-12, "min_jerk 终点")
close(sd, 0.0, 1e-12, "min_jerk 终点速度")
close(sa, 0.0, 1e-9, "min_jerk 终点加速度")

d = C.move_duration(0.1, P.P["v_line_max"], 1.0)
if d < 1.875 * 0.1 / P.P["v_line_max"] - 1e-9:
    raise SystemExit("FAIL: 移动时长没尊重峰值速度")

# ---------- 悬停 10 秒 ----------
plant = M.Plant()
ctl = C.Controller()
ball0 = np.array(P.P0)
for i in range(int(10.0 / P.P["dt"])):
    plant.step(ctl.update(plant, i * P.P["dt"]), dt=P.P["dt"])
drift = np.linalg.norm(plant.ball_center() - ball0)
if drift > 0.002:
    raise SystemExit("FAIL: 悬停漂移 %.3f mm" % (drift * 1000))
active = plant.tensions()[list(ctl.status()["support"])]
if np.min(active) < P.P["t_min"] - 1e-9 or np.max(active) > P.P["t_max"] + 1e-9:
    raise SystemExit("FAIL: 悬停张力越界 %r" % active)

# ---------- 100 mm 定点 ----------
plant = M.Plant()
ctl = C.Controller()
target = (P.P0[0] + 0.100, P.P0[1], P.P0[2])
ctl.start_move(target)
settled_at = None
for i in range(int(6.0 / P.P["dt"])):
    plant.step(ctl.update(plant, i * P.P["dt"]), dt=P.P["dt"])
    if np.linalg.norm(plant.ball_center() - np.array(target)) < 0.005:
        if settled_at is None:
            settled_at = i * P.P["dt"]
    else:
        settled_at = None
if settled_at is None or settled_at > 4.5:
    raise SystemExit("FAIL: 100 mm 定点 settle=%r" % settled_at)

# ---------- 8 选 4 在三个点上的结果 ----------
W = np.array([0.0, 0.0, P.P["m"] * P.G - P.P["tether_up"]])
for ball, want in [(P.P0, P.SUPPORT_P0), (P.P1, P.SUPPORT_P1), (P.P2, P.SUPPORT_P2)]:
    r = C.best_support(P.hub_of(ball), W)
    if tuple(r["idx"]) != want:
        raise SystemExit("FAIL: %r 支撑 %r != %r" % (ball, r["idx"], want))

# ---------- 交叉时合力不翻倍、不丢力（共享锚点相加） ----------
point = np.array(P.hub_of(P.P0))
T = C.crossfade_tensions(point, W, P.SUPPORT_P0, P.SUPPORT_P1, 0.5)
s = np.zeros(3)
for i, a in enumerate(ALL_ANCHORS):
    d = np.array(a) * P.MM - point
    s += T[i] * d / np.linalg.norm(d)
if np.linalg.norm(s - W) > 1e-6:
    raise SystemExit("FAIL: 交叉合力 %r != %r" % (s, W))

# ---------- 三点短跑：至少切一次，偏移 <100 mm ----------
plant = M.Plant()
ctl = C.Controller()
ctl.start_move(P.P1)
max_off = 0.0
for i in range(int(5.0 / P.P["dt"])):
    t = i * P.P["dt"]
    plant.step(ctl.update(plant, t), dt=P.P["dt"])
    ref = ctl.status()["p_ref"]
    max_off = max(max_off, np.linalg.norm(plant.ball_center() - ref))
if ctl.status()["switches"] != 0:
    raise SystemExit("FAIL: 固定支撑下不应切换")
if max_off > 0.100:
    raise SystemExit("FAIL: 跟踪偏移 %.1f mm" % (max_off * 1000))

# ---------- 实验开关：真的会切；瞬态大小只记录，不作验收 ----------
params = dict(P.P)
params["switching"] = True
plant = M.Plant(params=params)
ctl = C.Controller(params=params)
ctl.start_move((0.300, 0.520, 1.300))
for i in range(int(4.0 / params["dt"])):
    plant.step(ctl.update(plant, i * params["dt"]), dt=params["dt"])
if ctl.status()["switches"] < 1:
    raise SystemExit("FAIL: switching=True 时没有切换")

print("PASS")
