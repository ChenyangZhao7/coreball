"""轨迹、外环位置控制、张力分配与 1 kHz 张力伺服。"""
import math

import numpy as np

import dyn_model as M
import dyn_params as P
import tension
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


def smoothstep(x):
    x = min(max(x, 0.0), 1.0)
    return x * x * (3.0 - 2.0 * x)


def best_support(point, W):
    """8 选 4：四根都不超上限，按 margin - 0.005*ΣT 取最高。"""
    best = None
    for idx in tension.SUBSETS4:
        try:
            r = solve_force(point, W, idx, P.ANCHORS)
        except ValueError:
            continue
        if min(r["T"]) < -1e-9 or max(r["T"]) > P.P["t_max"]:
            continue
        score = r["margin"] - 0.005 * sum(r["T"])
        if best is None or score > best["score"]:
            best = dict(r, idx=list(idx), score=score)
    return best


def crossfade_tensions(point, W, old_idx, new_idx, lam):
    """旧/新组各解完整 W 的张力，再按 (1-lam)/lam 缩放；共享锚点相加。"""
    old = solve_force(point, W, old_idx, P.ANCHORS)
    new = solve_force(point, W, new_idx, P.ANCHORS)
    out = np.zeros(8)
    for j, i in enumerate(old_idx):
        out[i] += (1.0 - lam) * old["T"][j]
    for j, i in enumerate(new_idx):
        out[i] += lam * new["T"][j]
    return out


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
        self.active = set(self.support)
        self.switches = 0
        self.enable_switching = bool(self.p.get("switching", False))
        self.switching = False
        self.old_support = None
        self.new_support = None
        self.switch_t0 = 0.0
        self.last_supervisor = -1e9
        self.cooldown_until = -1e9
        self.abort = False

        self.T_target = np.zeros(8)
        self.integral = np.zeros(8)
        self.prev_measured = None
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

    def _outer(self, plant, t):
        rotation = M.quat_to_R(plant.q)
        offset = rotation @ np.array([0.0, 0.0, -self.p["ball_offset"]])
        p_ball = plant.r + offset
        v_ball = plant.v + np.cross(plant.w, offset)

        e = self.p_ref - p_ball
        ev = self.v_ref - v_ball
        W = (self.p["m"] * (self.a_ref + self.p["kp"] * e + self.p["kd"] * ev)
             + np.array([0.0, 0.0, self.p["m"] * P.G - self.p["tether_up"]]))
        W = self._feasible_force(plant.r, W)
        self.last_W = W

        self._supervise(plant, t, W)

        if self.switching:
            lam = smoothstep((t - self.switch_t0) / self.p["switch_s"])
            # 交叉期间只用静重：PD 的水平分量可能让新组在实测位置不可行，
            # 强行分配会出现负张力，球会直接掉下去。
            W_switch = np.array(
                [0.0, 0.0, self.p["m"] * P.G - self.p["tether_up"]])
            target = crossfade_tensions(
                tuple(plant.r), tuple(W_switch), self.old_support,
                self.new_support, lam)
            if lam >= 1.0:
                self.support = tuple(self.new_support)
                self.active = set(self.support)
                self.switching = False
                self.switches += 1
                self.cooldown_until = t + self.p["cooldown_s"]
                self.old_support = None
                self.new_support = None
        else:
            solved = solve_force(tuple(plant.r), tuple(W), self.support, P.ANCHORS)
            target = np.zeros(8)
            for j, i in enumerate(self.support):
                target[i] = solved["T"][j]

        for i in range(8):
            if i not in self.active:
                target[i] = self.p["idle_tension"]
        self.T_target = target

    def _feasible_force(self, point, W):
        """把期望力投影到当前支撑组能提供的范围内（保持重力分量）。

        PD 在边界上会要求一个四根线给不出的水平力；不投影就会出现负张力、
        线松掉。这里对「偏离重力」的部分做二分，找到最大可行比例。
        """
        W = np.asarray(W, dtype=float)
        gravity = np.array(
            [0.0, 0.0, self.p["m"] * P.G - self.p["tether_up"]])

        def ok(vec):
            try:
                r = solve_force(tuple(point), tuple(vec), self.support, P.ANCHORS)
            except ValueError:
                return False
            return (r["margin"] >= self.p["t_min"]
                    and min(r["T"]) >= -1e-9
                    and max(r["T"]) <= self.p["t_max"])

        if ok(W):
            return W
        lo, hi = 0.0, 1.0
        for _ in range(12):
            mid = 0.5 * (lo + hi)
            if ok(gravity + mid * (W - gravity)):
                lo = mid
            else:
                hi = mid
        return gravity + lo * (W - gravity)

    def _supervise(self, plant, t, W):
        if not self.enable_switching:
            return
        if self.switching or t < self.cooldown_until:
            return
        if t - self.last_supervisor < 1.0 / self.p["supervisor_hz"]:
            return
        self.last_supervisor = t

        # 按**实测**吊点选支撑：参考点跑在前面时，按参考选出的组可能在
        # 球的实际位置根本闭不上，切换后会直接掉下去。
        hub_ref = np.array(plant.r)
        # 选支撑组只看静重，不看瞬时加减速：否则加速段会把组换来换去
        W_static = np.array([0.0, 0.0, self.p["m"] * P.G - self.p["tether_up"]])
        best = best_support(tuple(hub_ref), tuple(W_static))
        if best is None or best["margin"] < self.p["switch_margin"]:
            return  # 没有余量足够好的替代组时，守着当前组
        try:
            current = solve_force(tuple(hub_ref), tuple(W_static),
                                  self.support, P.ANCHORS)
            current_score = current["margin"] - 0.005 * sum(current["T"])
            current_margin = current["margin"]
        except ValueError:
            current_score = -1e9
            current_margin = -1e9

        if tuple(best["idx"]) == tuple(self.support):
            return
        # 停着且当前组还绷得住时不要换：悬停不应该因为姿态微调去切支撑
        if not self.moving and current_margin >= self.p["t_min"]:
            return
        # 只有当前组余量掉到 1.0 N 以下才换；分数略高不构成切换理由
        if current_margin < self.p["switch_margin"]:
            self.switching = True
            self.old_support = tuple(self.support)
            self.new_support = tuple(best["idx"])
            self.switch_t0 = t
            self.active = set(self.old_support) | set(self.new_support)

    def _servo(self, plant):
        measured = plant.tensions()
        dt = plant.p["dt"]
        currents = np.zeros(8)
        rd = self.p["drum_r"]
        kt = self.p["kt"]
        if self.prev_measured is None:
            rate = np.zeros(8)
        else:
            rate = (measured - self.prev_measured) / dt

        for i in range(8):
            if i in self.active:
                desired = self.T_target[i]
                error = desired - measured[i]
                self.integral[i] = np.clip(
                    self.integral[i] + error * dt, -5.0, 5.0)
                feed = (desired * rd
                        + self.p["fric_b"] * plant.theta_dot[i]
                        + self.p["fric_c"] * np.tanh(plant.theta_dot[i] / 1e-4)) / kt
                currents[i] = (feed
                               + self.p["servo_kp"] * error
                               + self.p["servo_ki"] * self.integral[i]
                               - self.p["servo_kd"] * rate[i]
                               - self.p["servo_kv"] * plant.theta_dot[i])
            elif measured[i] > 0.15:
                currents[i] = -self.p["idle_pay"]
            else:
                currents[i] = (self.p["idle_tension"] * rd / kt
                               + self.p["servo_kp"] * (self.p["idle_tension"] - measured[i]))

        self.prev_measured = measured.copy()
        return np.clip(currents, -self.p["i_max"], self.p["i_max"])

    def update(self, plant, t):
        self._reference(t)
        self.steps += 1
        if self.steps == 1 or self.steps % self.p["control_every"] == 0:
            self._outer(plant, t)
        return self._servo(plant)

    def status(self):
        return {
            "p_ref": self.p_ref.copy(),
            "v_ref": self.v_ref.copy(),
            "support": list(self.support),
            "active": sorted(self.active),
            "switching": self.switching,
            "switches": self.switches,
            "abort": self.abort,
        }
