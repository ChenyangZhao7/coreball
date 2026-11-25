"""调试台遥测与 manual jog 的纯函数测试（不需要 Blender）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import telemetry as T


def eq(a, b, msg):
    if a != b:
        raise SystemExit("FAIL: %s (%r != %r)" % (msg, a, b))


def close(a, b, msg, tol=1e-6):
    if abs(a - b) > tol:
        raise SystemExit("FAIL: %s (%r !~ %r)" % (msg, a, b))


RES = {
    "support": [0, 1, 2, 3],
    "support_names": ["A1", "A2", "A3", "A4"],
    "idle_count": 4,
    "lengths": [648.27, 1101.68, 531.27, 545.10],
    "T": [2.05, 1.83, 2.10, 1.83],
    "margin": 1.83,
    "closed": True,
}

ANCHORS = [
    (-760.0, 217.0, 1729.0), (603.0, 950.0, 1550.0),
    (-300.0, 217.0, 1729.0), (-603.0, 950.0, 1550.0),
    (760.0, 217.0, 1550.0), (-603.0, 200.0, 1729.0),
    (603.0, 400.0, 1640.0), (603.0, 600.0, 1640.0),
]

# ---------- snapshot ----------
s = T.snapshot(
    ball_mm=(-380.0, 520.0, 1300.0),
    hub_mm=(-380.0, 520.0, 1460.0),
    res=RES,
    blocked=False,
    last="去",
    body="winch",
    expr="acting",
    yaw=0.7,
    goal="come",
    anchors=ANCHORS,
    t=1700000000.0,
)
eq(s["ball"], [-380.0, 520.0, 1300.0], "球心")
eq(s["hub"], [-380.0, 520.0, 1460.0], "吊点")
eq(s["support"], [0, 1, 2, 3], "支撑索引")
eq(s["support_names"], ["A1", "A2", "A3", "A4"], "支撑名")
eq(s["tensions"], [2.05, 1.83, 2.1, 1.83], "张力")
eq(s["lengths"], [648.0, 1102.0, 531.0, 545.0], "线长")
eq(s["margin"], 1.83, "最松")
eq(s["closed"], True, "力封闭")
eq(s["blocked"], False, "否决")
eq(s["last"], "去", "最后指令")
eq(s["expr"], "acting", "表情")
eq(s["yaw"], 0.7, "朝向")
eq(s["goal"], "come", "目标")
eq(s["t"], 1700000000.0, "时间戳")
eq(len(s["anchors"]), 8, "锚点数量")
eq(s["anchors"][0], [-760.0, 217.0, 1729.0], "锚点坐标")

s2 = T.snapshot(ball_mm=(0, 0, 0), hub_mm=(0, 0, 160), res=None)
eq(s2["support"], [], "无解时支撑为空")
eq(s2["tensions"], [], "无解时张力为空")
eq(s2["margin"], None, "无解时最松为 None")
eq(s2["closed"], None, "无解时力封闭为 None")
eq(s2["anchors"], [], "不传锚点时不硬编码")

# ---------- normalize_jog ----------
eq(T.normalize_jog([100, -20, 3]), (100.0, -20.0, 3.0), "正常速度")
eq(T.normalize_jog([0, 0, 0]), (0.0, 0.0, 0.0), "停下")
eq(T.normalize_jog([9999, 0, 0]), (T.MAX_JOG_MM_S, 0.0, 0.0), "限速")
eq(T.normalize_jog([0, 9999, 0]), (0.0, T.MAX_JOG_MM_S, 0.0), "限速 y")
eq(T.normalize_jog("nope"), None, "非数组")
eq(T.normalize_jog([1, 2]), None, "长度不对")
eq(T.normalize_jog([float("nan"), 0, 0]), None, "NaN")
eq(T.normalize_jog([True, 0, 0]), None, "布尔不算数")

# ---------- jog_step ----------
p, v = T.jog_step((0, 0, 0), (100, 0, 0), 0.1)
eq(p, (10.0, 0.0, 0.0), "积分 0.1 s")
eq(v, (100.0, 0.0, 0.0), "实际速度")

p, v = T.jog_step((0, 0, 0), (100, 0, 0), 10.0)
eq(p, (10.0, 0.0, 0.0), "单帧 dt 封顶 0.1 s")

p, v = T.jog_step((0, 0, 0), (100, 0, 0), 0.1, clamp=lambda q: (0.0, 0.0, 0.0))
eq(p, (0.0, 0.0, 0.0), "夹住后不动")
eq(v, (0.0, 0.0, 0.0), "夹住后实际速度为 0")

p, v = T.jog_step((0, 0, 0), (100, 0, 0), 0.1, clamp=lambda q: (5.0, q[1], q[2]))
eq(p, (5.0, 0.0, 0.0), "部分夹住")
eq(v, (50.0, 0.0, 0.0), "部分夹住后的实际速度")

p, v = T.jog_step((0, 0, 0), (100, 0, 0), 0.0)
eq(p, (0.0, 0.0, 0.0), "dt=0 不动")
eq(v, (0.0, 0.0, 0.0), "dt=0 速度为 0")

print("PASS")
