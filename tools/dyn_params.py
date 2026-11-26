"""CoreBall 动态仿真的全部参数（SI 单位）。

参数来源和置信度见 docs/superpowers/specs/2026-11-26-dynamic-sim-design.md §7。
锚点在这里统一转成米；传给 tension.solve_force 时也必须用米制锚点。
"""
import hashlib
import json

import tension

MM = 0.001
ANCHORS = [tuple(c * MM for c in a) for a in tension.ALL_ANCHORS]

G = tension.G
TETHER_UP = tension.TETHER_UP
T_MIN = tension.T_MIN
T_MAX = tension.T_MAX

P0 = (-0.380, 0.520, 1.300)
P1 = (-0.180, 0.520, 1.300)
P2 = (-0.380, 0.700, 1.300)

SUPPORT_P0 = (1, 2, 3, 5)
SUPPORT_P1 = (0, 1, 3, 4)
SUPPORT_P2 = (1, 3, 4, 5)

P = {
    "m": tension.BALL_MASS,
    "ball_offset": 0.160,
    "com_offset": 0.083,
    # 绕吊点的转动惯量（已按刚体绕吊点估计，不再加平行轴项）
    "inertia": (8.0e-4, 8.0e-4, 4.0e-4),
    "rope_ea": 6000.0,
    "rope_zeta": 0.15,
    "drum_r": 0.017,
    "drum_j": 2.0e-5,
    "kt": 0.235,
    "i_max": 1.2,
    "tau_hold": 0.4,
    "v_line_max": 0.356,
    "fric_c": 0.01,
    "fric_b": 1.0e-3,
    "rot_damp": 0.002,
    "current_tau": 5.0e-4,
    "attachment": "ring",
    # 30 mm 会在 5 Hz 张力极限环（见 docs/09）；10 mm 是仿真验证过的上限。
    "ring_r": 0.010,
    "ring_z": -0.001,
    "ear_angles": (26.6, 124.6, 233.2, 279.0),
    "dt": 2.0e-4,
    "control_every": 5,
    "supervisor_hz": 30.0,
    "switch_s": 0.3,
    "cooldown_s": 0.3,
    "kp": 64.0,
    "kd": 16.0,
    # 张力环高增益会自激；0.005 A/N + 无积分在 10 mm 环上稳定。
    "servo_kp": 0.005,
    "servo_ki": 0.0,
    "idle_tension": 0.05,
    "idle_pay": 0.10,
    "tether_up": TETHER_UP,
    "t_min": T_MIN,
    "t_max": T_MAX,
}


def hub_of(ball):
    return (ball[0], ball[1], ball[2] + P["ball_offset"])


def _plain(value):
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


def params_hash(params=None):
    data = _plain(P if params is None else params)
    raw = json.dumps(data, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
