"""三个动态场景、指标、CSV/PNG/summary/replay 输出与 CLI。"""
import argparse
import csv
import json
import os

import numpy as np

import dyn_control as C
import dyn_model as M
import dyn_params as P


# ---------------- 指标 ----------------
def _dist(y, target):
    y = np.asarray(y, dtype=float)
    target = np.asarray(target, dtype=float)
    return np.linalg.norm(y - target, axis=1)


def settle_time(t, y, target, band=0.005, hold=0.5, t0=None):
    t = np.asarray(t)
    d = _dist(y, target)
    start = 0 if t0 is None else int(np.searchsorted(t, t0 - 1e-12))
    origin = 0.0 if t0 is None else float(t0)
    entered = None
    for j in range(start, len(t)):
        if d[j] <= band:
            if entered is None:
                entered = j
            if t[j] - t[entered] >= hold:
                return float(t[entered] - origin)
        else:
            entered = None
    return None


def return_time(t, y, target, t0, band=0.005, hold=0.5):
    return settle_time(t, y, target, band=band, hold=hold, t0=t0)


def peak_to_peak(y):
    """真正的峰峰值：点集里最远两点的距离（不是相对首点）。"""
    y = np.asarray(y, dtype=float)
    if len(y) < 2:
        return 0.0
    diff = y[:, None, :] - y[None, :, :]
    return float(np.linalg.norm(diff, axis=2).max())


def max_drift(y, target):
    d = _dist(y, target)
    return float(d.max()) if len(d) else 0.0


def rms_drift(y, target):
    d = _dist(y, target)
    return float(np.sqrt(np.mean(d ** 2))) if len(d) else 0.0


def slack_stats(t, tensions, active):
    """每根主动绳各自的松弛累计时间，返回 (总和, 最大值)。"""
    t = np.asarray(t, dtype=float)
    tensions = np.asarray(tensions, dtype=float)
    active = list(active)
    per = np.zeros(len(active))
    for i in range(len(t) - 1):
        dt = t[i + 1] - t[i]
        for k, idx in enumerate(active):
            if tensions[i, idx] < 0.30:
                per[k] += dt
    return float(per.sum()), float(per.max() if len(per) else 0.0)


def slack_time(t, tensions, active):
    """兼容旧调用：返回所有主动绳松弛时间的总和。"""
    return slack_stats(t, tensions, active)[0]


# ---------------- 运行 ----------------
def _new_run(params=None, ball=P.P0):
    p = dict(P.P if params is None else params)
    plant = M.Plant(params=p, ball_target=ball)
    ctl = C.Controller(params=p, target_ball=ball)
    return p, plant, ctl


def _empty_series():
    return {"t": [], "ball": [], "hub": [], "q": [], "w": [],
            "vel": [], "current": [], "tensions": [], "lengths": [],
            "support": [], "phases": [], "ref": [], "switching": []}


def _record(series, t, plant, ctl, phase=""):
    status = ctl.status()
    series["t"].append(float(t))
    series["ball"].append(plant.ball_center().copy())
    series["hub"].append(plant.r.copy())
    series["q"].append(plant.q.copy())
    series["w"].append(plant.w.copy())
    series["vel"].append(plant.v.copy())
    series["current"].append(plant.current.copy())
    series["tensions"].append(plant.tensions().copy())
    series["lengths"].append(plant.cable_lengths().copy())
    series["support"].append(tuple(status["support"]))
    series["phases"].append(phase)
    series["ref"].append(np.asarray(status["p_ref"], dtype=float).copy())
    series["switching"].append(bool(status["switching"]))


def _finalize(series):
    out = {}
    for key, value in series.items():
        if key in ("support", "phases", "switching"):
            out[key] = list(value)
        else:
            out[key] = np.array(value, dtype=float)
    return out


def _simulate(plant, ctl, duration, record_hz=100.0, push=0.0,
              push_at=None, spin=False):
    dt = plant.p["dt"]
    steps = int(round(duration / dt))
    every = max(1, int(round(1.0 / (record_hz * dt))))
    series = _empty_series()
    pushed = push_at is None

    for i in range(steps + 1):
        t = i * dt
        if not pushed and t >= push_at:
            impulse = np.array([push, 0.0, 0.0])
            if spin:
                r_ball = plant.ball_center() - plant.r
                plant.v = plant.v + impulse / plant.m
                plant.w = plant.w + np.cross(r_ball, impulse) / plant.inertia
            else:
                plant.v = plant.v + impulse / plant.m
            pushed = True
        if i % every == 0:
            _record(series, t, plant, ctl)
        if i < steps:
            plant.step(ctl.update(plant, t), dt=dt)
    return _finalize(series)


def _thresholds(name):
    if name == "hover":
        return {"drift_max_mm": 5.0, "tension_min_n": 0.30,
                "tension_max_n": 20.0, "slack_s": 0.0}
    if name == "three_points":
        return {"pp_mm": 2.0, "settle_s": 4.5}
    if name == "push":
        # 冲量瞬间允许 50 ms 的单根绳卸载；超过就是真松了
        return {"return_s": 2.0, "max_offset_mm": 80.0, "slack_s": 0.05}
    return {}


def run_hover(params=None, duration=60.0, settle=10.0, record_hz=100.0):
    duration = float(duration)
    if duration <= 0:
        raise ValueError("duration 必须大于 0")
    settle = min(float(settle), duration * 0.95)
    p, plant, ctl = _new_run(params)
    series = _simulate(plant, ctl, duration, record_hz, push_at=None)
    t, ball = series["t"], series["ball"]
    mask = t >= settle
    target = np.array(P.P0)
    active = list(ctl.status()["support"])
    ten = series["tensions"][mask]
    slack_total, slack_max = slack_stats(t[mask], ten, active)
    metrics = {
        "drift_max_mm": max_drift(ball[mask], target) * 1000.0,
        "drift_rms_mm": rms_drift(ball[mask], target) * 1000.0,
        "tension_min_n": float(np.min(ten[:, active])),
        "tension_max_n": float(np.max(ten[:, active])),
        "slack_s": slack_total,
        "slack_max_s": slack_max,
        "switches": int(ctl.status()["switches"]),
    }
    th = _thresholds("hover")
    passed = (metrics["drift_max_mm"] < th["drift_max_mm"]
              and metrics["tension_min_n"] >= th["tension_min_n"] - 1e-9
              and metrics["tension_max_n"] <= th["tension_max_n"] + 1e-9
              and metrics["slack_s"] <= 1e-9)
    return {"scenario": "hover", "params_hash": P.params_hash(p),
            "series": series, "metrics": metrics, "thresholds": th,
            "passed": bool(passed), "final_ball": ball[-1].tolist()}


def run_three_points(params=None, dwell=5.0, record_hz=100.0):
    p, plant, ctl = _new_run(params)
    targets = [np.array(P.P1), np.array(P.P2)]
    d1 = C.move_duration(np.linalg.norm(targets[0] - np.array(P.P0)),
                         p["v_line_max"], 1.0)
    d2 = C.move_duration(np.linalg.norm(targets[1] - targets[0]),
                         p["v_line_max"], 1.0)
    start2 = d1 + dwell
    total = start2 + d2 + dwell
    dt = p["dt"]
    every = max(1, int(round(1.0 / (record_hz * dt))))
    series = _empty_series()
    ctl.start_move(targets[0])
    started2 = False

    for i in range(int(round(total / dt)) + 1):
        t = i * dt
        if not started2 and t >= start2:
            ctl.start_move(targets[1])
            started2 = True
        if t < d1:
            phase = "move1"
        elif t < start2:
            phase = "dwell1"
        elif t < start2 + d2:
            phase = "move2"
        else:
            phase = "dwell2"
        if i % every == 0:
            _record(series, t, plant, ctl, phase)
        if i < int(round(total / dt)):
            plant.step(ctl.update(plant, t), dt=dt)

    series = _finalize(series)
    t, ball, phases = series["t"], series["ball"], series["phases"]
    pps = []
    settles = []
    for idx, target in enumerate(targets):
        label = "dwell%d" % (idx + 1)
        mask = np.array([ph == label for ph in phases])
        if not mask.any():
            pps.append(None)
        else:
            tw = t[mask]
            bw = ball[mask]
            keep = tw >= tw[-1] - min(2.0, dwell)
            pps.append(peak_to_peak(bw[keep]) * 1000.0)
        t0 = 0.0 if idx == 0 else start2
        settles.append(settle_time(t, ball, target, band=0.005, hold=0.5, t0=t0))

    pp_mm = max([x for x in pps if x is not None], default=float("inf"))
    settle_s = max([x for x in settles if x is not None], default=float("inf"))
    sw_mask = np.array(series["switching"], dtype=bool)
    if sw_mask.any():
        switch_offset_mm = float(np.max(np.linalg.norm(
            series["ball"][sw_mask] - series["ref"][sw_mask], axis=1))) * 1000.0
    else:
        switch_offset_mm = 0.0
    metrics = {
        "pp_mm": pp_mm,
        "settle_s": settle_s,
        "switches": int(ctl.status()["switches"]),
        "switch_offset_mm": switch_offset_mm,
    }
    th = _thresholds("three_points")
    passed = (pp_mm < th["pp_mm"] and settle_s < th["settle_s"]
              and settle_s != float("inf"))
    return {"scenario": "three_points", "params_hash": P.params_hash(p),
            "series": series, "metrics": metrics, "thresholds": th,
            "passed": bool(passed), "final_ball": ball[-1].tolist()}


def run_push(params=None, impulse=0.2, push_at=10.0, duration=12.0,
             record_hz=100.0):
    duration = float(duration)
    if duration <= 0:
        raise ValueError("duration 必须大于 0")
    push_at = min(float(push_at), duration * 0.5)
    p, plant, ctl = _new_run(params)
    series = _simulate(plant, ctl, duration, record_hz,
                       push=impulse, push_at=push_at)
    t, ball = series["t"], series["ball"]
    mask = t >= push_at
    target = np.array(P.P0)
    active = list(ctl.status()["support"])
    ten = series["tensions"][mask]
    return_s = return_time(t, ball, target, t0=push_at)
    dist = _dist(ball, target)
    left = np.where((t >= push_at) & (dist > 0.005))[0]
    first_t0 = push_at if len(left) == 0 else float(t[left[0]])
    first_entry_s = settle_time(t, ball, target, band=0.005, hold=0.0,
                                t0=first_t0)
    slack_total, slack_max = slack_stats(t[mask], ten, active)
    metrics = {
        "return_s": return_s,
        "first_entry_s": first_entry_s,
        "max_offset_mm": max_drift(ball[mask], target) * 1000.0,
        "overshoot_mm": max(0.0, float(np.max(ball[mask, 0]) - target[0])) * 1000.0,
        "tension_min_n": float(np.min(ten[:, active])),
        "tension_max_n": float(np.max(ten[:, active])),
        "slack_s": slack_total,
        "slack_max_s": slack_max,
    }
    th = _thresholds("push")
    passed = (return_s is not None and return_s < th["return_s"]
              and metrics["max_offset_mm"] < th["max_offset_mm"]
              and metrics["slack_s"] <= th["slack_s"])
    return {"scenario": "push", "params_hash": P.params_hash(p),
            "series": series, "metrics": metrics, "thresholds": th,
            "passed": bool(passed), "final_ball": ball[-1].tolist()}


def run_push_spin(params=None, impulse=0.2, push_at=10.0, duration=12.0,
                  record_hz=100.0):
    p, plant, ctl = _new_run(params)
    series = _simulate(plant, ctl, duration, record_hz,
                       push=impulse, push_at=push_at, spin=True)
    t, ball = series["t"], series["ball"]
    mask = t >= push_at
    target = np.array(P.P0)
    return_s = return_time(t, ball, target, t0=push_at)
    metrics = {
        "return_s": return_s,
        "max_offset_mm": max_drift(ball[mask], target) * 1000.0,
        "note": "report only; literal ball-center impulse",
    }
    return {"scenario": "push_spin", "params_hash": P.params_hash(p),
            "series": series, "metrics": metrics, "thresholds": {},
            "passed": None, "final_ball": ball[-1].tolist()}


# ---------------- 输出 ----------------
def _write_csv(result, path):
    s = result["series"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        header = (["t", "ball_x", "ball_y", "ball_z",
                   "hub_x", "hub_y", "hub_z",
                   "vx", "vy", "vz",
                   "qw", "qx", "qy", "qz", "wx", "wy", "wz"]
                  + ["I%d" % (i + 1) for i in range(8)]
                  + ["T%d" % (i + 1) for i in range(8)]
                  + ["L%d" % (i + 1) for i in range(8)])
        writer.writerow(header)
        for i in range(len(s["t"])):
            row = ([s["t"][i]] + list(s["ball"][i]) + list(s["hub"][i])
                   + list(s["vel"][i]) + list(s["q"][i]) + list(s["w"][i])
                   + list(s["current"][i])
                   + list(s["tensions"][i]) + list(s["lengths"][i]))
            writer.writerow(["%.9g" % x for x in row])


def _write_png(result, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    s = result["series"]
    t = s["t"]
    ball_mm = s["ball"] * 1000.0
    tilt = 2.0 * np.degrees(np.arccos(
        np.clip(np.abs(s["q"][:, 0]), 0.0, 1.0)))

    fig, axes = plt.subplots(3, 1, figsize=(9, 8), sharex=True)
    for k, name in enumerate("xyz"):
        axes[0].plot(t, ball_mm[:, k], label="ball " + name)
    axes[0].set_ylabel("ball (mm)")
    axes[0].legend(loc="best", ncol=3, fontsize=8)
    for i in range(8):
        axes[1].plot(t, s["tensions"][:, i], label="T%d" % (i + 1), linewidth=1)
    axes[1].axhline(0.30, color="0.4", linestyle="--", linewidth=0.8)
    axes[1].set_ylabel("tension (N)")
    axes[1].legend(loc="best", ncol=4, fontsize=7)
    axes[2].plot(t, tilt, color="tab:orange")
    axes[2].set_ylabel("tilt (deg)")
    axes[2].set_xlabel("time (s)")
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def write_outputs(result, out_dir, no_plot=False):
    os.makedirs(out_dir, exist_ok=True)
    name = result["scenario"]
    _write_csv(result, os.path.join(out_dir, name + ".csv"))
    if not no_plot:
        _write_png(result, os.path.join(out_dir, name + ".png"))

    summary = {
        "scenario": name,
        "params_hash": result["params_hash"],
        "metrics": result["metrics"],
        "thresholds": result["thresholds"],
        "passed": result["passed"],
    }
    with open(os.path.join(out_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    s = result["series"]
    med = float(np.median(np.diff(s["t"]))) if len(s["t"]) >= 2 else 0.01
    step = max(1, int(round(1.0 / (10.0 * med))))
    replay = []
    for i in range(0, len(s["t"]), step):
        replay.append({
            "t": float(s["t"][i]),
            "ball": [float(x) for x in s["ball"][i]],
            "hub": [float(x) for x in s["hub"][i]],
            "vel": [float(x) for x in s["vel"][i]],
            "support": list(s["support"][i]),
            # 原始 8 根张力；/state 的 4 根可按 support 取子集
            "tensions": [float(x) for x in s["tensions"][i]],
            "lengths": [float(x) for x in s["lengths"][i]],
            "currents": [float(x) for x in s["current"][i]],
        })
    with open(os.path.join(out_dir, "replay.json"), "w", encoding="utf-8") as f:
        json.dump(replay, f, ensure_ascii=False)


def sweep_params(out_dir="out/sim/sweep"):
    os.makedirs(out_dir, exist_ok=True)
    rows = []
    for key in ("rope_ea", "rope_zeta", "inertia", "fric_c", "kt"):
        for scale in (0.5, 2.0):
            q = dict(P.P)
            if key == "inertia":
                q[key] = tuple(x * scale for x in q[key])
            else:
                q[key] = q[key] * scale
            hover = run_hover(params=q, duration=5.0, settle=1.0)
            push = run_push(params=q, push_at=1.0, duration=4.0)
            rows.append({
                "param": key,
                "scale": scale,
                "hover_drift_mm": hover["metrics"]["drift_max_mm"],
                "hover_slack_s": hover["metrics"]["slack_s"],
                "hover_passed": hover["passed"],
                "push_return_s": push["metrics"]["return_s"],
                "push_passed": push["passed"],
            })
    with open(os.path.join(out_dir, "sweep.json"), "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    with open(os.path.join(out_dir, "sweep.md"), "w", encoding="utf-8") as f:
        f.write("| param | scale | hover drift mm | hover slack s | hover | push return s | push |\n")
        f.write("|---|---|---|---|---|---|---|\n")
        for r in rows:
            f.write("| %s | %.1f | %.2f | %.2f | %s | %s | %s |\n" % (
                r["param"], r["scale"], r["hover_drift_mm"], r["hover_slack_s"],
                r["hover_passed"],
                "-" if r["push_return_s"] is None else "%.2f" % r["push_return_s"],
                r["push_passed"]))
    return rows


# ---------------- CLI ----------------
def main(argv=None):
    ap = argparse.ArgumentParser(description="CoreBall 动态仿真")
    ap.add_argument("--scenario", default="all",
                    choices=("hover", "three", "push", "spin", "all"))
    ap.add_argument("--all", action="store_true", help="等价于 --scenario all")
    ap.add_argument("--out", default="out/sim")
    ap.add_argument("--duration", type=float, default=60.0)
    ap.add_argument("--no-plot", action="store_true")
    ap.add_argument("--sweep", action="store_true")
    args = ap.parse_args(argv)
    if args.all:
        args.scenario = "all"

    if args.sweep:
        sweep_params(os.path.join(args.out, "sweep"))
        print("wrote", os.path.join(args.out, "sweep", "sweep.json"))
        return 0

    runners = {
        "hover": lambda: run_hover(duration=args.duration),
        "three": run_three_points,
        "push": run_push,
        "spin": run_push_spin,
    }
    if args.scenario == "all":
        names = ["hover", "three", "push", "spin"]
    else:
        names = [args.scenario]

    results = {}
    for name in names:
        result = runners[name]()
        results[name] = result
        out_dir = os.path.join(args.out, name) if args.scenario == "all" else args.out
        write_outputs(result, out_dir, no_plot=args.no_plot)
        print("%-12s %s  %s" % (
            name, "PASS" if result["passed"] else
            ("report" if result["passed"] is None else "FAIL"),
            {k: (round(v, 3) if isinstance(v, (int, float)) else v)
             for k, v in result["metrics"].items()}))

    if args.scenario == "all":
        with open(os.path.join(args.out, "summary.json"), "w", encoding="utf-8") as f:
            json.dump({k: {"metrics": v["metrics"], "passed": v["passed"]}
                       for k, v in results.items()}, f, ensure_ascii=False, indent=2)
    return 0 if all(v["passed"] is not False for v in results.values()) else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
