"""六自由度刚体 + 8 根缆绳 + 8 个卷筒的动力学。"""
import math

import numpy as np

import dyn_params as P
import tension

EPS = 1e-9


# ---------------- 四元数 ----------------
def quat_normalize(q):
    q = np.asarray(q, dtype=float)
    n = np.linalg.norm(q)
    return q / n if n > 1e-15 else np.array([1.0, 0.0, 0.0, 0.0])


def quat_mul(a, b):
    w1, x1, y1, z1 = a
    w2, x2, y2, z2 = b
    return np.array([
        w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
        w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
        w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
        w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2,
    ])


def quat_to_R(q):
    w, x, y, z = quat_normalize(q)
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
        [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
        [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
    ])


class Plant:
    def __init__(self, params=None, ball_target=P.P0, support=P.SUPPORT_P0,
                 attachment=None):
        self.p = dict(P.P if params is None else params)
        if attachment is not None:
            self.p["attachment"] = attachment
        self.support = tuple(support)
        self.m = float(self.p["m"])
        self.inertia = np.array(self.p["inertia"], dtype=float)
        self.anchors = np.array(P.ANCHORS, dtype=float)

        self.r = np.array(P.hub_of(ball_target), dtype=float)
        self.v = np.zeros(3)
        self.q = np.array([1.0, 0.0, 0.0, 0.0])
        self.w = np.zeros(3)

        self.theta = np.zeros(8)
        self.theta_dot = np.zeros(8)
        self.current = np.zeros(8)

        self.L0_init = self._initial_lengths()
        self.L0 = self.L0_init.copy()
        self.current = self._feedforward()

    # ---------------- 几何 ----------------
    def attachment_points(self):
        mode = self.p["attachment"]
        if mode == "point":
            return np.tile(self.r, (8, 1))

        Rb = quat_to_R(self.q)
        r_ring = float(self.p["ring_r"])
        z_ring = float(self.p["ring_z"])
        ears = np.deg2rad(np.array(self.p["ear_angles"], dtype=float))
        out = np.empty((8, 3))
        for i, anchor in enumerate(self.anchors):
            d = anchor - self.r
            horizontal = Rb.T @ np.array([d[0], d[1], 0.0])
            ang = math.atan2(horizontal[1], horizontal[0])
            if mode == "ears4":
                diff = np.abs(np.angle(np.exp(1j * (ears - ang))))
                ang = ears[int(np.argmin(diff))]
            local = np.array([r_ring * math.cos(ang),
                              r_ring * math.sin(ang), z_ring])
            out[i] = self.r + Rb @ local
        return out

    def cable_lengths(self):
        d = self.anchors - self.attachment_points()
        return np.linalg.norm(d, axis=1)

    def cable_rates(self):
        p = self.attachment_points()
        d = self.anchors - p
        length = np.linalg.norm(d, axis=1)
        u = d / np.maximum(length[:, None], EPS)
        r_i = p - self.r
        v_att = self.v[None, :] + np.cross(np.broadcast_to(self.w, (8, 3)), r_i)
        return -np.sum(u * v_att, axis=1)

    def tensions(self):
        length = self.cable_lengths()
        rate = self.cable_rates()
        k = self.p["rope_ea"] / np.maximum(self.L0, 1e-6)
        c = 2.0 * self.p["rope_zeta"] * np.sqrt(k * self.m / 4.0)
        strain = length - self.L0
        t = np.where(strain > 0.0, k * strain + c * rate, 0.0)
        return np.maximum(t, 0.0)

    def cable_force(self):
        p = self.attachment_points()
        d = self.anchors - p
        length = np.linalg.norm(d, axis=1)
        u = d / np.maximum(length[:, None], EPS)
        return np.sum(self.tensions()[:, None] * u, axis=0)

    def net_force(self):
        return (self.cable_force()
                + np.array([0.0, 0.0, -self.m * P.G + self.p["tether_up"]]))

    def net_torque(self):
        p = self.attachment_points()
        d = self.anchors - p
        length = np.linalg.norm(d, axis=1)
        u = d / np.maximum(length[:, None], EPS)
        r_i = p - self.r
        tau = np.sum(np.cross(r_i, self.tensions()[:, None] * u), axis=0)

        r_com = quat_to_R(self.q) @ np.array([0.0, 0.0, -self.p["com_offset"]])
        tau += np.cross(r_com, np.array([0.0, 0.0, -self.m * P.G]))
        tau -= self.p["rot_damp"] * self.w
        return tau

    def ball_center(self):
        return self.r + quat_to_R(self.q) @ np.array(
            [0.0, 0.0, -self.p["ball_offset"]])

    # ---------------- 初始状态 ----------------
    def _initial_lengths(self):
        length = self.cable_lengths()
        w0 = (0.0, 0.0, self.m * P.G - self.p["tether_up"])
        solved = tension.solve_force(tuple(self.r), w0, self.support, P.ANCHORS)
        l0 = length + 0.005
        for j, i in enumerate(self.support):
            k = self.p["rope_ea"] / max(length[i], 1e-6)
            l0[i] = length[i] - solved["T"][j] / k
        self._static_T = list(solved["T"])
        return l0

    def _feedforward(self):
        current = np.zeros(8)
        for j, i in enumerate(self.support):
            current[i] = self._static_T[j] * self.p["drum_r"] / self.p["kt"]
        return np.clip(current, -self.p["i_max"], self.p["i_max"])

    # ---------------- 积分 ----------------
    def step(self, currents=None, dt=None):
        dt = float(self.p["dt"] if dt is None else dt)

        cmd = np.zeros(8) if currents is None else np.asarray(currents, dtype=float)
        cmd = np.clip(cmd, -self.p["i_max"], self.p["i_max"])
        alpha = min(1.0, dt / max(self.p["current_tau"], EPS))
        self.current += (cmd - self.current) * alpha

        # 卷筒：先算旧张力，更新卷筒和放线长度
        t_old = self.tensions()
        tau_m = np.clip(self.p["kt"] * self.current,
                        -self.p["tau_hold"], self.p["tau_hold"])
        tau_f = self.p["fric_c"] * np.tanh(self.theta_dot / 1e-4)
        theta_ddot = (tau_m - self.p["drum_r"] * t_old
                      - self.p["fric_b"] * self.theta_dot - tau_f) / self.p["drum_j"]
        self.theta_dot += theta_ddot * dt
        vmax = self.p["v_line_max"] / self.p["drum_r"]
        self.theta_dot = np.clip(self.theta_dot, -vmax, vmax)
        self.theta += self.theta_dot * dt
        self.L0 = self.L0_init - self.p["drum_r"] * self.theta

        # 刚体：用更新后的绳长算力
        p = self.attachment_points()
        d = self.anchors - p
        length = np.linalg.norm(d, axis=1)
        u = d / np.maximum(length[:, None], EPS)
        t = self.tensions()

        force = (np.sum(t[:, None] * u, axis=0)
                 + np.array([0.0, 0.0, -self.m * P.G + self.p["tether_up"]]))
        r_i = p - self.r
        tau = np.sum(np.cross(r_i, t[:, None] * u), axis=0)
        r_com = quat_to_R(self.q) @ np.array([0.0, 0.0, -self.p["com_offset"]])
        tau += np.cross(r_com, np.array([0.0, 0.0, -self.m * P.G]))
        tau -= self.p["rot_damp"] * self.w

        self.v += (force / self.m) * dt
        self.r += self.v * dt

        alpha_w = (tau - np.cross(self.w, self.inertia * self.w)) / self.inertia
        self.w += alpha_w * dt
        qdot = 0.5 * quat_mul(self.q, np.array([0.0, *self.w]))
        self.q = quat_normalize(self.q + qdot * dt)
