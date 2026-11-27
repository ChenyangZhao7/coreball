"""指挥场景的运行时：面板刷新 + 禁区回弹。

由 指挥.bat 用 `blender <blend> --python cmd_runtime.py` 启动。
直接双击 .blend 不会跑这个文件：线和球照样跟随，只是没有面板。

所有数值单位：毫米（界面）与米（Blender），在边界转换。
"""
import sys
import json
import math
import socket
import threading
import queue
import time
from pathlib import Path

import bpy
import blf

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "tools"))

import tension as T  # noqa: E402
import body as BODYMAP  # noqa: E402
import telemetry as TEL  # noqa: E402

ACTIONS_PATH = HERE / "actions.json"

HUB_GAP_MM = 160.0      # 球心 → 吊点中心
NECK_X, NECK_Y = 0.0, 890.0
NECK_R = 210.0
BOOTH_HX = 820.0        # 左右墙 x = ±820
BOOTH_Y0, BOOTH_Y1 = 0.0, 1100.0
PRACTICAL_Y0 = 250.0    # 实用区：不进入后墙前 250 mm（锚点凸包外）
BALL_R, WALL_GAP = 40.0, 5.0
NECK_CLEAR = NECK_R + BALL_R   # 球心硬约束：球面不进入 r210 圆柱

TELEMETRY_ADDR = ("127.0.0.1", 4591)
JOG_TIMEOUT = 0.35      # 控制页每 50 ms 发一次；超过这个时间没包就停


def _clamp_walls(x, y):
    m = BALL_R + WALL_GAP
    return (max(-BOOTH_HX + m, min(BOOTH_HX - m, x)),
            max(BOOTH_Y0 + m, PRACTICAL_Y0, min(BOOTH_Y1 - m, y)))


def load_actions(path=None):
    p = Path(path) if path else ACTIONS_PATH
    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or not isinstance(data.get("actions"), dict):
        raise ValueError("动作表缺少 actions")
    return data


def resolve(actions, src, key):
    table = (actions.get("bindings") or {}).get(src) or {}
    return table.get(str(key))


def intent_point(actions, name, points, current_mm):
    act = (actions.get("actions") or {}).get(name)
    if not act:
        return None
    if "target" in act:
        p = points.get(act["target"])
        return list(p) if p is not None else None
    if "delta" in act:
        return [current_mm[i] + float(act["delta"][i]) for i in range(3)]
    return None


def move_profile(d, vmax=356.0, rebound=4.0):
    """五次多项式 S 曲线 + 到位后 4mm 越冲再收住。d 毫米，vmax 毫米/秒。"""
    if d <= 1e-9:
        return {"T": 0.0, "pos": lambda t: 0.0}
    dur = 1.875 * d / vmax
    settle = 0.4

    def pos(t):
        if t <= 0:
            return 0.0
        if t < dur:
            u = t / dur
            x = d * (10 * u ** 3 - 15 * u ** 4 + 6 * u ** 5)
        elif t <= dur + settle:
            # 平滑越冲：起点和终点都是 0 斜率，峰值就是 rebound
            x = d + 0.5 * rebound * (1 - math.cos(2 * math.pi * (t - dur) / settle))
        else:
            x = d
        return x

    return {"T": dur, "pos": pos}


def start_move(p0, p1, style, now):
    d = ((p1[0] - p0[0]) ** 2 + (p1[1] - p0[1]) ** 2 + (p1[2] - p0[2]) ** 2) ** 0.5
    return {
        "active": d > 0.5,
        "p0": list(p0), "p1": list(p1), "d": d, "t0": now,
        "hes": float(style.get("hesitate", 0.0)),
        "profile": move_profile(d, float(style.get("vmax", 356.0)),
                                float(style.get("rebound", 4.0))),
    }


def move_at(m, now):
    if not m.get("active"):
        return list(m["p1"])
    t = now - m["t0"] - m["hes"]
    if t < 0:
        return list(m["p0"])
    prof = m["profile"]
    if t > prof["T"] + 1.0:
        m["active"] = False
        return list(m["p1"])
    f = prof["pos"](t) / m["d"] if m["d"] > 0 else 1.0
    return [m["p0"][i] + (m["p1"][i] - m["p0"][i]) * f for i in range(3)]


def scene_points():
    """所有 TGT_xxx 空物体 → {xxx: [x,y,z] mm}，用户可以自己在 Blender 里拖。"""
    pts = {}
    for ob in bpy.data.objects:
        if ob.name.startswith("TGT_"):
            p = ob.matrix_world.translation
            pts[ob.name[4:].lower()] = [p.x * 1000.0, p.y * 1000.0, p.z * 1000.0]
    return pts


def current_ball_mm():
    t = active_target()
    if t is None:
        return [0.0, 0.0, 0.0]
    p = t.matrix_world.translation
    return [p.x * 1000.0, p.y * 1000.0, p.z * 1000.0]


def active_target():
    name = "CMD_TARGET" if BODY["active"] == "winch" else "ROVER_ROOT"
    return bpy.data.objects.get(name)


def route_intent(actions, msg, points, current_mm):
    name = msg.get("intent")
    conf = float(msg.get("conf", 1.0))
    if conf < float(actions.get("min_conf", 0.0)):
        return {"kind": "ignored"}
    if name == "goto":
        p = msg.get("point")
        if not (isinstance(p, (list, tuple)) and len(p) == 3):
            return {"kind": "bad_target", "name": name}
        try:
            p = [float(v) for v in p]
        except (TypeError, ValueError):
            return {"kind": "bad_target", "name": name}
        if BODY["active"] != "winch":
            p[2] = 0.0
        q = list(clamp_ball(p))
        r = {"kind": "move", "point": q, "style": {}, "name": name}
        if max(abs(q[i] - p[i]) for i in range(3)) > 1.0:
            r["requested"] = p      # 安全层改写前的原始目标，遥测里如实上报
        return r
    if name == "expression":
        expr = msg.get("name")
        if expr not in EXPRESSIONS:
            return {"kind": "bad_target", "name": name}
        return {"kind": "expression", "expr": expr, "name": name}
    act = (actions.get("actions") or {}).get(name)
    if act is None:
        return {"kind": "unknown", "name": name}
    if act.get("mount"):
        return {"kind": "mount", "body": act["mount"], "name": name}
    r = BODYMAP.map_intent(BODY["active"], name, points, current_mm)
    if r is None:
        p = intent_point(actions, name, points, current_mm)
        if p is None:
            return {"kind": "bad_target", "name": name}
        r = {"kind": "move", "point": p}
    r["name"] = name
    if r["kind"] == "move":
        q = list(clamp_ball(r["point"]))
        if max(abs(q[i] - r["point"][i]) for i in range(3)) > 1.0:
            r["requested"] = list(r["point"])   # 安全层改写前的原始目标
        r["point"] = q
        r["style"] = (actions.get("styles") or {}).get(act.get("style", "normal"), {})
    return r


def start_udp(port=4590, q=None):
    """后台线程只收包进队列，绝不碰 bpy。"""
    q = q if q is not None else INTENT_Q

    def loop():
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.bind(("127.0.0.1", port))
        except OSError as e:
            print("CoreBall: UDP 端口 %d 打不开：%s" % (port, e))
            return
        while True:
            data, _ = s.recvfrom(8192)
            try:
                msg = json.loads(data.decode("utf-8"))
            except Exception:
                continue
            if isinstance(msg, dict) and msg.get("intent"):
                try:
                    q.put_nowait(msg)
                except queue.Full:
                    pass

    t = threading.Thread(target=loop, daemon=True)
    t.start()
    return t


def begin_move(point_mm, style):
    MOVE.clear()
    MOVE.update(start_move(current_ball_mm(), point_mm, style, time.monotonic()))


def face_person():
    t = active_target()
    head = bpy.data.objects.get("PERSON_HEAD")
    if t is None or head is None:
        return
    d = head.matrix_world.translation - t.matrix_world.translation
    yaw = BODYMAP.face_yaw(d.x, d.y)    # 脸窗在 +Y；绕 Z 正转会把 +Y 转到 −X
    if BODY["active"] == "winch":
        br = bpy.data.objects.get("ball_root")
        if br is not None:
            br.rotation_euler = (0.0, 0.0, yaw)
    else:
        t.rotation_euler = (0.0, 0.0, yaw)


def set_core_light(on):
    m = bpy.data.materials.get("ROVER_LED")
    if m is None or not m.use_nodes:
        return
    node = m.node_tree.nodes.get("Principled BSDF")
    if node is not None:
        node.inputs["Emission Strength"].default_value = 2.5 if on else 0.05


def mount(name):
    """把核心从一具身体挪到另一具；未完成的目标交给新身体继续表达。"""
    if name not in BODYMAP.BODIES:
        STATE["last"] = "没有这个身体"
        return False
    BODY["active"] = name
    winch = name == "winch"
    br = bpy.data.objects.get("ball_root")
    if br is not None:
        br.hide_viewport = not winch
        br.hide_render = not winch
    set_core_light(not winch)
    MOVE["active"] = False
    _stop_jog()
    goal = STATE.get("goal")
    if goal:
        apply_intent({"intent": goal, "src": "handoff"})
    return True


def apply_intent(msg):
    if msg.get("intent") == "jog":
        v = TEL.normalize_jog(msg.get("v"))
        if v is None:
            STATE["last"] = "jog 参数不对"
            return
        MOVE["active"] = False
        JOG.update(v=v, t=time.monotonic(), last=0.0)
        moving = any(v)
        STATE["last"] = "手动" if moving else "手动停止"
        if not moving:
            STATE["goal"] = None
        set_expression("acting" if moving else "idle")
        return

    try:
        actions = load_actions()
    except Exception:
        STATE["last"] = "动作表坏了"
        return
    r = route_intent(actions, msg, scene_points(), current_ball_mm())
    kind = r["kind"]
    print("INTENT", msg, "->", kind, r.get("point"), flush=True)
    if kind == "move":
        _stop_jog()
        begin_move(r["point"], r["style"])
        set_expression("acting")
        STATE["last"] = r["name"]
        STATE["goal"] = r["name"]
        STATE["requested"] = r.get("requested")
    elif kind == "mount":
        if mount(r["body"]):
            STATE["last"] = "换到" + BODYMAP.BODIES[r["body"]]["name"]
    elif kind == "refuse":
        MOVE["active"] = False
        _stop_jog()
        set_expression("idle")
        STATE["requested"] = None
        STATE["last"] = r["reason"]
        print("REFUSE", r["reason"], flush=True)
    elif kind == "hold":
        MOVE["active"] = False
        _stop_jog()
        STATE["goal"] = None
        STATE["requested"] = None
        set_expression("idle")
        STATE["last"] = "停"
    elif kind == "face":
        face_person()
        STATE["last"] = "看我"
    elif kind == "expression":
        set_expression(r["expr"])
        STATE["last"] = "表情：" + r["expr"]
    elif kind == "unknown":
        STATE["last"] = "不认识的指令"
    elif kind == "ignored":
        STATE["last"] = "置信度太低"
    else:
        STATE["last"] = "目标点不存在"


def status_text(res):
    if res is None:
        return "几何退化"
    if res["margin"] >= T.T_MIN:
        return "力封闭正常"
    return "力封闭失效（最松 %.2f N）" % res["margin"]


def status_color(res):
    if res is None:
        return (0.85, 0.70, 0.30, 1.0)
    if res["margin"] >= T.T_MIN:
        return (0.35, 0.78, 0.52, 1.0)
    return (0.85, 0.30, 0.28, 1.0)


def hud_lines(hub_mm, res, blocked=False, last=None, body="winch", pos_mm=None):
    if body != "winch":
        p = pos_mm or (0.0, 0.0, 0.0)
        lines = ["小机器人 (%.0f, %.0f) 地面" % (p[0], p[1]),
                 "2 轴 · 地面 · 无线缆"]
        if last:
            lines.append("指令：%s" % last)
        return lines
    pos = "吊点 (%d, %d, %d)" % (hub_mm[0], hub_mm[1], hub_mm[2])
    if res is None:
        lines = [pos, "线长 mm  —", "张力 N   —", status_text(None)]
    else:
        lengths = "线长 mm  " + " ".join("%4.0f" % v for v in res["lengths"])
        force = "张力 N   " + " ".join("%4.2f" % v for v in res["T"])
        lines = [pos, lengths, force,
                 "最松 %.2f N · %s" % (res["margin"], status_text(res))]
        if res.get("support_names"):
            lines.insert(3, "支撑 %s · 闲散 %d" %
                         (" ".join(res["support_names"]), res.get("idle_count", 0)))
    if blocked:
        lines[-1] = "安全层否决 · " + lines[-1]
    if last:
        lines.append("指令：%s" % last)
    return lines


EXPRESSIONS = {
    "idle":      ((0.12, 0.72, 1.00), 0.35),
    "listening": ((1.00, 0.62, 0.30), 1.60),
    "acting":    ((1.00, 0.78, 0.45), 3.00),
}


def set_expression(name):
    # 灯带去掉后，情绪改由脸窗点阵的发光色/强度表达
    STATE["expr"] = name
    m = bpy.data.materials.get("Pixel")
    if m is None or not m.use_nodes:
        return None
    color, strength = EXPRESSIONS.get(name, EXPRESSIONS["idle"])
    b = m.node_tree.nodes.get("Principled BSDF")
    if b is None:
        return None
    b.inputs["Emission Color"].default_value = (*color, 1.0)
    b.inputs["Emission Strength"].default_value = strength
    return (color, strength)


def clamp_ball(p):
    """先把球夹在三面墙内，再推出脖子圆柱（球心留出球半径）。"""
    x, y, z = p
    x, y = _clamp_walls(x, y)
    dx, dy = x - NECK_X, y - NECK_Y
    r = (dx * dx + dy * dy) ** 0.5
    if r < NECK_CLEAR:
        # Blender 坐标是 float32，轴线上的点带 ~1e-5 mm 噪声；
        # 阈值取得比噪声大，避免把噪声放大成错误方向。
        if r < 0.5:
            x, y = NECK_X + NECK_CLEAR, NECK_Y
        else:
            k = NECK_CLEAR / r
            x, y = NECK_X + dx * k, NECK_Y + dy * k
    x, y = _clamp_walls(x, y)
    return (x, y, z)


def panel_origin(region_h):
    """面板左上角在视口里的位置：避开标题栏、Text Info 和左侧工具栏。"""
    return (110, region_h - 200)


# ---------------- 运行时 ----------------
STATE = {"hub_mm": None, "res": None, "blocked": False, "last": None,
         "goal": None, "body": "winch", "pos_mm": None,
         "ball_mm": None, "expr": "idle", "requested": None}
BODY = {"active": "winch"}
INTENT_Q = queue.Queue(maxsize=64)
MOVE = {"active": False}
JOG = {"v": (0.0, 0.0, 0.0), "t": 0.0, "last": 0.0}
_TELE = {"sock": None}
_busy = False
_last = 0.0
_HANDLER = None
_TIMERS = {"on": False, "tele": False}


def _stop_jog():
    JOG.update(v=(0.0, 0.0, 0.0), t=0.0, last=0.0)


def _ball_yaw():
    br = bpy.data.objects.get("ball_root")
    return float(br.rotation_euler.z) if br is not None else 0.0


def push_telemetry():
    """把最新状态发给本机控制桥；没有位置时返回 False。"""
    if STATE.get("ball_mm") is None:
        return False
    snap = TEL.snapshot(
        STATE.get("ball_mm"), STATE.get("hub_mm"), STATE.get("res"),
        blocked=STATE.get("blocked", False), last=STATE.get("last"),
        body=STATE.get("body", "winch"), expr=STATE.get("expr", "idle"),
        yaw=_ball_yaw(), goal=STATE.get("goal"), anchors=T.ALL_ANCHORS,
        requested=STATE.get("requested"),
        t=time.time())
    if _TELE["sock"] is None:
        _TELE["sock"] = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        _TELE["sock"].sendto(json.dumps(snap, ensure_ascii=False).encode("utf-8"),
                             TELEMETRY_ADDR)
        return True
    except OSError:
        return False


def _telemetry_tick():
    try:
        push_telemetry()
    except Exception as e:
        print("CoreBall 遥测发送失败:", e, flush=True)
    return 0.1


def _tick(scene=None, depsgraph=None):
    global _busy, _last
    import time
    if _busy:
        return
    now = time.monotonic()
    if now - _last < 0.1:
        return
    _last = now
    _busy = True
    try:
        STATE["body"] = BODY["active"]
        if BODY["active"] != "winch":
            p_mm = current_ball_mm()
            STATE.update(pos_mm=p_mm, ball_mm=p_mm, hub_mm=None, res=None, blocked=False)
            return
        t = bpy.data.objects.get("CMD_TARGET")
        h = bpy.data.objects.get("HUB_ROOT")
        if t is None or h is None:
            return
        p = t.matrix_world.translation
        p_mm = (p.x * 1000.0, p.y * 1000.0, p.z * 1000.0)
        c = clamp_ball(p_mm)
        moved = max(abs(c[i] - p_mm[i]) for i in range(3))
        if moved > 1e-3:
            t.location = (c[0] / 1000.0, c[1] / 1000.0, c[2] / 1000.0)
            STATE["blocked"] = True
            # 同一帧里 HUB_ROOT 还没跟上，直接用夹紧后的球心推吊点
            hub_mm = (c[0], c[1], c[2] + HUB_GAP_MM)
        else:
            STATE["blocked"] = False
            hw = h.matrix_world.translation
            hub_mm = (hw.x * 1000.0, hw.y * 1000.0, hw.z * 1000.0)
        try:
            res = T.solve_selected(hub_mm)
        except Exception:
            res = None
        STATE.update(ball_mm=(c[0], c[1], c[2]), hub_mm=hub_mm, res=res)
    finally:
        _busy = False


def _draw():
    if STATE["hub_mm"] is None and STATE["pos_mm"] is None:
        return
    try:
        x0, top = panel_origin(bpy.context.region.height)
    except Exception:
        x0, top = panel_origin(800)
    lines = hud_lines(STATE["hub_mm"], STATE["res"], STATE["blocked"], STATE["last"],
                      STATE["body"], STATE["pos_mm"])
    res = STATE["res"]
    if res is None or STATE["blocked"]:
        color = (0.85, 0.70, 0.30, 1.0)
    elif res["margin"] < T.T_MIN:
        color = (0.85, 0.30, 0.28, 1.0)
    else:
        color = (0.78, 0.84, 0.90, 1.0)
    blf.size(0, 13)
    for i, ln in enumerate(lines):
        blf.color(0, *color)
        blf.position(0, x0, top - i * 17, 0)
        blf.draw(0, ln)


def _move_tick():
    now = time.monotonic()
    if MOVE.get("active"):
        p = move_at(MOVE, now)
        if BODY["active"] == "winch":
            p = clamp_ball(p)
        t = active_target()
        if t is not None:
            t.location = (p[0] / 1000.0, p[1] / 1000.0, p[2] / 1000.0)
            if BODY["active"] == "rover":
                dx = MOVE["p1"][0] - MOVE["p0"][0]
                dy = MOVE["p1"][1] - MOVE["p0"][1]
                if abs(dx) + abs(dy) > 1e-6:
                    t.rotation_euler = (0.0, 0.0, math.atan2(dx, dy))
        if not MOVE.get("active"):
            set_expression("idle")
            STATE["goal"] = None
    elif JOG["t"]:
        if now - JOG["t"] > JOG_TIMEOUT:
            # 死手开关：控制页关掉/断线后自己停
            _stop_jog()
            set_expression("idle")
            STATE["goal"] = None
            STATE["last"] = "手动停止"
        else:
            t = active_target()
            if t is not None:
                dt = now - JOG["last"] if JOG["last"] else 1.0 / 30.0
                clamp = clamp_ball if BODY["active"] == "winch" else None
                nxt, applied = TEL.jog_step(current_ball_mm(), JOG["v"], dt, clamp)
                t.location = (nxt[0] / 1000.0, nxt[1] / 1000.0, nxt[2] / 1000.0)
                JOG["last"] = now
                if BODY["active"] == "rover" and abs(applied[0]) + abs(applied[1]) > 1e-6:
                    t.rotation_euler = (0.0, 0.0, math.atan2(applied[0], applied[1]))
    return 1.0 / 30.0


def _intent_tick():
    while True:
        try:
            msg = INTENT_Q.get_nowait()
        except queue.Empty:
            break
        apply_intent(msg)
    return 0.05


_KEYCODES = {
    "0": "ZERO", "1": "ONE", "2": "TWO", "3": "THREE", "4": "FOUR",
    "5": "FIVE", "6": "SIX", "7": "SEVEN", "8": "EIGHT", "9": "NINE",
}


class CMDBALL_OT_intent(bpy.types.Operator):
    bl_idname = "cmdball.intent"
    bl_label = "CoreBall Intent"
    intent: bpy.props.StringProperty()

    def execute(self, context):
        apply_intent({"intent": self.intent, "src": "key"})
        return {'PASS_THROUGH'}


def register_keys(actions):
    kc = bpy.context.window_manager.keyconfigs.addon
    if kc is None:
        return
    km = kc.keymaps.get("3D View")
    if km is None:
        km = kc.keymaps.new(name="3D View", space_type='VIEW_3D')
    for k, name in ((actions.get("bindings") or {}).get("key") or {}).items():
        code = _KEYCODES.get(str(k))
        if code is None:
            continue
        kmi = km.keymap_items.new("cmdball.intent", code, 'PRESS')
        kmi.properties.intent = name


def register():
    global _HANDLER, _last
    if _tick not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_tick)
    if _HANDLER is None:
        _HANDLER = bpy.types.SpaceView3D.draw_handler_add(_draw, (), 'WINDOW', 'POST_PIXEL')
    try:
        bpy.utils.register_class(CMDBALL_OT_intent)
    except ValueError:
        pass
    try:
        register_keys(load_actions())
    except Exception as e:
        print("CoreBall: 动作表没读成，键盘没绑：", e)
    start_udp(4590)
    if not _TIMERS["on"]:
        bpy.app.timers.register(_move_tick, persistent=True)
        bpy.app.timers.register(_intent_tick, persistent=True)
        _TIMERS["on"] = True
    if not _TIMERS["tele"]:
        bpy.app.timers.register(_telemetry_tick, persistent=True)
        _TIMERS["tele"] = True
    _last = 0.0
    _tick()
    set_expression("idle")
    _telemetry_tick()
    print("CoreBall 指挥运行时已启动：拖 CMD_TARGET，或按键 1/2/3/4/5/0")


if __name__ == "__main__":
    register()
