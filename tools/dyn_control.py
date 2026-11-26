"""轨迹、外环位置控制、张力分配与 1 kHz 张力伺服。"""
import math

import numpy as np

import dyn_model as M
import dyn_params as P
from tension import solve_force


def min_jerk(t, T):
    """五次多项式：返回 (s, sdot, sddot)，s 从 0 到 1。"""
    if T <= 0.0:
        return 1.0, 0.0, 0.0
    tau = min(max(t / T, 0.0), 1.0)
    s = 10 * tau ** 3 - 15 * tau ** 4 + 6 * tau ** 5
    sd = (30 * tau ** 2 - 60 * tau ** 3 + 30 * tau ** 4) / T
    sa = (60 * tau - 180 * tau ** 2 + 120 * tau ** 3) / (T * T)
    return s, sd, sa


def move_duration(distance, vmax, amax):
    if distance < 1e-9:
        return 0.0
    return max(1.875 * distance / vmax,
               math.sqrt(5.7735 * distance / amax), 0.5)


class Controller:
    def __init__(self, params=None, target_ball=P.P0):
        self.p = dict(P.P if params is None else params)
        self.target = np.array(target_ball, dtype=float)
        self.p_ref = self.target.copy()
        self.v_ref = np.zeros(3)
        self.a_ref = np.zeros(3)
        self.p0 = self.target.copy()
        self.move_t0 = 0.0
        self.move_T = 0.0
        self.moving = False
        self.move_pending = False

        self.support = tuple(P.SUPPORT_P0)
        self.switches = 0
        self.switching = False
        self.abort = False

        self.T_target = np.zeros(8)
        self.integral = np.zeros(8)
        self.steps = 0
        self.last_W = None

    def start_move(self, target_ball, duration=None):
        self.pending_target = np.array(target_ball, dtype=float)
        self.pending_duration = duration
        self.move_pending = True

    def _reference(self, t):
        if self.move_pending:
            self.p0 = self.p_ref.copy()
            self.target = self.pending_target.copy()
            distance = np.linalg.norm(self.target - self.p0)
            self.move_T = (self.pending_duration if self.pending_duration is not None
                           else move_duration(distance, self.p["v_line_max"], 1.0))
            self.move_t0 = t
            self.moving = True
            self.move_pending = False

        if not self.moving:
            self.p_ref = self.target.copy()
            self.v_ref = np.zeros(3)
            self.a_ref = np.zeros(3)
            return

        elapsed = t - self.move_t0
        if elapsed >= self.move_T:
            self.p_ref = self.target.copy()
            self.v_ref = np.zeros(3)
            self.a_ref = np.zeros(3)
            self.moving = False
            return

        s, sd, sa = min_jerk(elapsed, self.move_T)
        delta = self.target - self.p0
        self.p_ref = self.p0 + s * delta
        self.v_ref = sd * delta
        self.a_ref = sa * delta

    def _outer(self, plant):
        rotation = M.quat_to_R(plant.q)
        offset = rotation @ np.array([0.0, 0.0, -self.p["ball_offset"]])
        p_ball = plant.r + offset
        v_ball = plant.v + np.cross(plant.w, offset)

        e = self.p_ref - p_ball
        ev = self.v_ref - v_ball
        W = (self.p["m"] * (self.a_ref + self.p["kp"] * e + self.p["kd"] * ev)
             + np.array([0.0, 0.0, self.p["m"] * P.G - self.p["tether_up"]]))
        self.last_W = W

        solved = solve_force(tuple(plant.r), tuple(W), self.support, P.ANCHORS)
        target = np.full(8, self.p["idle_tension"])
        for j, i in enumerate(self.support):
            target[i] = solved["T"][j]
        self.T_target = target

    def _servo(self, plant):
        measured = plant.tensions()
        dt = plant.p["dt"]
        currents = np.zeros(8)
        rd = self.p["drum_r"]
        kt = self.p["kt"]

        for i in range(8):
            if i in self.support:
                desired = self.T_target[i]
                error = desired - measured[i]
                self.integral[i] = np.clip(
                    self.integral[i] + error * dt, -5.0, 5.0)
                feed = (desired * rd
                        + self.p["fric_b"] * plant.theta_dot[i]
                        + self.p["fric_c"] * np.tanh(plant.theta_dot[i] / 1e-4)) / kt
                currents[i] = (feed
                               + self.p["servo_kp"] * error
                               + self.p["servo_ki"] * self.integral[i])
            elif measured[i] > 0.15:
                currents[i] = -self.p["idle_pay"]
            else:
                currents[i] = (self.p["idle_tension"] * rd / kt
                               + self.p["servo_kp"] * (self.p["idle_tension"] - measured[i]))

        return np.clip(currents, -self.p["i_max"], self.p["i_max"])

    def update(self, plant, t):
        self._reference(t)
        self.steps += 1
        if self.steps == 1 or self.steps % self.p["control_every"] == 0:
            self._outer(plant)
        return self._servo(plant)

    def status(self):
        return {
            "p_ref": self.p_ref.copy(),
            "v_ref": self.v_ref.copy(),
            "support": list(self.support),
            "switching": self.switching,
            "switches": self.switches,
            "abort": self.abort,
        }
