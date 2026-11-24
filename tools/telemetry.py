"""调试台用的遥测快照与手动 jog 积分（纯 Python，不依赖 Blender）。

Blender 侧每 100 ms 把 snapshot() 的结果发到 127.0.0.1:4591；
本地桥缓存最新一帧，控制页用 GET /state 读。

单位：位置 mm，速度 mm/s，张力 N。
"""
import math

MAX_JOG_MM_S = 400.0   # 手动速度上限
MAX_DT = 0.1           # 单帧最多积 0.1 s，卡顿时不会瞬移


def _is_num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def normalize_jog(v):
    """校验并限制 [vx, vy, vz]（mm/s）；不合法返回 None。"""
    if not isinstance(v, (list, tuple)) or len(v) != 3:
        return None
    if not all(_is_num(x) for x in v):
        return None
    out = [float(x) for x in v]
    speed = math.hypot(out[0], out[1], out[2])
    if speed > MAX_JOG_MM_S:
        k = MAX_JOG_MM_S / speed
        out = [x * k for x in out]
    return tuple(out)


def jog_step(pos, vel, dt, clamp=None):
    """按速度积分一帧，返回 (新位置, 实际速度)。

    clamp 是位置约束函数（例如三面墙 + 脖子圆柱）；被夹住时实际速度会变小。
    """
    dt = max(0.0, min(MAX_DT, float(dt)))
    p0 = tuple(float(x) for x in pos)
    if dt <= 0 or not any(vel):
        return p0, (0.0, 0.0, 0.0)

    p = tuple(p0[i] + float(vel[i]) * dt for i in range(3))
    if clamp is not None:
        p = tuple(float(x) for x in clamp(p))
    applied = tuple((p[i] - p0[i]) / dt for i in range(3))
    return p, applied


def _vec(p, digits=2):
    if p is None:
        return None
    return [round(float(x), digits) for x in p]


def snapshot(ball_mm, hub_mm, res=None, *, blocked=False, last=None,
             body="winch", expr="idle", goal=None, anchors=None, t=None):
    """一帧调试遥测。res 为 tension.solve_selected() 的结果，可为 None。"""
    out = {
        "t": float(t) if t is not None else None,
        "body": body,
        "ball": _vec(ball_mm),
        "hub": _vec(hub_mm),
        "blocked": bool(blocked),
        "last": last,
        "goal": goal,
        "expr": expr,
        "anchors": [_vec(a) for a in (anchors or [])],
        "support": [],
        "support_names": [],
        "idle": 0,
        "lengths": [],
        "tensions": [],
        "margin": None,
        "closed": None,
    }
    if res:
        out["support"] = list(res.get("support") or [])
        out["support_names"] = list(res.get("support_names") or [])
        out["idle"] = int(res.get("idle_count") or 0)
        out["lengths"] = [round(float(x)) for x in (res.get("lengths") or [])]
        out["tensions"] = [round(float(x), 3) for x in (res.get("T") or [])]
        if res.get("margin") is not None:
            out["margin"] = round(float(res["margin"]), 3)
        if res.get("closed") is not None:
            out["closed"] = bool(res["closed"])
    return out
