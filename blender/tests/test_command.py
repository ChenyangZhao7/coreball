"""无头验收：指挥场景的父子关系、Hook、面板与禁区回弹。

用法：
  blender -b blender/out/cmd/coreball_command.blend --python-exit-code 1 --python blender/tests/test_command.py
"""
import bpy
import sys
import os
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "tools"))


def fail(msg):
    print("FAIL:", msg)
    sys.exit(1)


# ---------- Task 1：控制层 ----------
if "CMD_TARGET" not in bpy.data.objects:
    fail("没有 CMD_TARGET")
if "HUB_ROOT" not in bpy.data.objects:
    fail("没有 HUB_ROOT")

t = bpy.data.objects["CMD_TARGET"]
if bpy.data.objects["ball_root"].parent != t:
    fail("ball_root 没挂到 CMD_TARGET")

if (bpy.data.objects["hub_plate"].matrix_world.translation
        - Vector((-0.38, 0.52, 1.46))).length > 0.001:
    fail("吊点被父级偏移了：%s" % (bpy.data.objects["hub_plate"].matrix_world.translation,))
if (bpy.data.objects["ball_root"].matrix_world.translation
        - Vector((-0.38, 0.52, 1.30))).length > 0.001:
    fail("球被父级偏移了：%s" % (bpy.data.objects["ball_root"].matrix_world.translation,))

hub_objs = list(bpy.data.collections["04_吊点"].objects)
bad = [o.name for o in hub_objs if o.parent != bpy.data.objects["HUB_ROOT"]]
if bad:
    fail("这些吊点对象没挂到 HUB_ROOT: %s" % bad)

before = bpy.data.objects["ball_root"].matrix_world.translation.copy()
hp = bpy.data.objects["hub_plate"].matrix_world.translation.copy()
t.location.x += 0.2
bpy.context.view_layer.update()
after = bpy.data.objects["ball_root"].matrix_world.translation
hp2 = bpy.data.objects["hub_plate"].matrix_world.translation
if abs((after - before).x - 0.2) > 1e-5:
    fail("球没跟着走")
if abs((hp2 - hp).x - 0.2) > 1e-5:
    fail("吊点没跟着走")


# ---------- Task 2：四线与供电线跟随 ----------
# Hook 只作用在求值后的几何上（曲线控制点本身不变），所以查网格顶点。
def mesh_world_verts(name):
    ob = bpy.data.objects[name]
    dg = bpy.context.evaluated_depsgraph_get()
    ev = ob.evaluated_get(dg)
    me = ev.to_mesh()
    pts = [ev.matrix_world @ v.co for v in me.vertices]
    ev.to_mesh_clear()
    return pts


for i in range(1, 9):
    ob = bpy.data.objects["cable_%d" % i]
    hooks = [m for m in ob.modifiers if m.type == 'HOOK']
    if not hooks or hooks[0].object.name != "lug_%d" % i:
        fail("cable_%d 没 hook 到 lug_%d" % (i, i))

bpy.data.objects["CMD_TARGET"].location.y -= 0.25
bpy.context.view_layer.update()
for i in range(1, 9):
    lug = bpy.data.objects["lug_%d" % i].matrix_world.translation
    d = min((v - lug).length for v in mesh_world_verts("cable_%d" % i))
    if d > 0.002:
        fail("cable_%d 末端离挂耳 %.2f mm" % (i, d * 1000))

# 线起点必须等于 tension 里的墙平面锚点（1 mm）
import tension as T
for i, want in enumerate(T.ALL_ANCHORS, 1):
    p = bpy.data.objects["cable_%d" % i].data.splines[0].points[0].co
    got = Vector((p.x, p.y, p.z)) * 1000.0
    if (got - Vector(want)).length > 1.0:
        fail("cable_%d 起点不是新锚点 A%d：%s" % (i, i, tuple(got)))


# ---------- Task 3：面板文本 ----------
from cmd_runtime import hud_lines, status_text, status_color
import tension as T

res = T.solve_selected((-380.0, 520.0, 1460.0))
joined = "\n".join(hud_lines((-380.0, 520.0, 1460.0), res))
for want in ["-380", "520", "1460", "1331", "645", "766", "661",
             "2.77", "2.34", "支撑 A2 A3 A4 A6"]:
    if want not in joined:
        fail("面板缺 %s" % want)

bad = T.solve_selected((-775.0, 45.0, 1300.0))
if "失效" not in status_text(bad):
    fail("失效没写出来")
if status_color(bad)[0] < 0.6:
    fail("失效没变红")

blocked_lines = "\n".join(hud_lines((-380.0, 890.0, 1460.0), res, blocked=True))
if "安全层否决" not in blocked_lines:
    fail("禁区拦住时面板没写安全层否决")


# ---------- Task 4：禁区回弹 ----------
from cmd_runtime import clamp_ball

a = clamp_ball((0.0, 890.0, 1300.0))
if abs((a[0] ** 2 + (a[1] - 890.0) ** 2) ** 0.5 - 250.0) > 1e-6:
    fail("轴线没推到 250（r210 圆柱 + 球半径 40）")
if a[2] != 1300.0:
    fail("回弹改了高度")

b = clamp_ball((-380.0, 520.0, 1300.0))
if b != (-380.0, 520.0, 1300.0):
    fail("禁区外被误推")

# Blender 坐标是 float32：轴线上的点会带 ~1e-5 mm 噪声，方向必须仍是 +X
a2 = clamp_ball((0.0, 889.9999857, 1300.0))
if abs(a2[0] - 250.0) > 1e-3 or abs(a2[1] - 890.0) > 1e-3:
    fail("轴线回弹方向错了：%s" % (a2,))


# ---------- Task 5：handler 端到端 ----------
import cmd_runtime as R
bpy.data.objects["CMD_TARGET"].location = (0.0, 0.890, 1.300)
bpy.context.view_layer.update()
R._last = 0.0
R._tick()
p = bpy.data.objects["CMD_TARGET"].location
if abs(p.x * 1000.0 - 250.0) > 0.5 or abs(p.y * 1000.0 - 890.0) > 0.5:
    fail("handler 回弹方向错了：%s" % (tuple(p),))
if R.STATE["hub_mm"] is None or R.STATE["res"] is None:
    fail("handler 没算出面板状态")

# 面板必须用夹紧后的位置，不能用夹紧前
hm = R.STATE["hub_mm"]
if abs(hm[0] - p.x * 1000.0) > 0.5 or abs(hm[1] - p.y * 1000.0) > 0.5:
    fail("夹紧后面板还是旧位置：%s vs %s" % (hm, tuple(p)))
if not R.STATE["blocked"]:
    fail("被安全层拦住却没标记 blocked")

# 刚启动时 register() 必须立刻有数据，不能等第一次拖动
R.STATE.update(hub_mm=None, res=None)
R._last = 0.0
R.register()
if R.STATE["hub_mm"] is None:
    fail("register() 后面板还是空的")

# A1–A4 在新几何里共面；吊点落在这个平面上 → 应判为不可飞（不误报 OK）
R._last = 0.0
bpy.data.objects["CMD_TARGET"].location = (-0.380, 0.520, 1.64745)
bpy.context.view_layer.update()
R._tick()
if R.STATE["res"] is not None and R.STATE["res"]["closed"]:
    fail("A1–A4 平面上的吊点被误判为可飞")

# 面板位置必须在标题栏和左上角文字下面
if R.panel_origin(800)[1] > 800 - 150:
    fail("面板太高，会压在标题栏上")
if R.panel_origin(800)[0] < 80:
    fail("面板太靠左，会压在工具栏上")

# 供电线的 Hook 也要在
for name, idx, target in (("wire_1", 1, "tether_sheave"), ("wire_2", 0, "tether_sheave")):
    hooks = [m for m in bpy.data.objects[name].modifiers if m.type == 'HOOK']
    if not hooks or hooks[0].object.name != target:
        fail("%s 没 hook 到 %s" % (name, target))
    if list(hooks[0].vertex_indices) != [idx]:
        fail("%s 的 Hook 索引错了" % name)

# ---------- Task 6：调试遥测与手动 jog ----------
import json
import socket
import time

import telemetry as TEL

R._last = 0.0
bpy.data.objects["CMD_TARGET"].location = (-0.380, 0.520, 1.300)
bpy.context.view_layer.update()
R._tick()
if R.STATE["ball_mm"] is None or R.STATE["hub_mm"] is None:
    fail("_tick 没记录球/吊点位置")
snap = TEL.snapshot(R.STATE["ball_mm"], R.STATE["hub_mm"], R.STATE["res"],
                    anchors=T.ALL_ANCHORS)
if len(snap["anchors"]) != 8:
    fail("遥测没有 8 个锚点")
if not snap["support"] or not snap["tensions"]:
    fail("遥测没有支撑/张力")

# 真正发一包 UDP，确认字段和地址都对
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.bind(("127.0.0.1", 0))
s.settimeout(2.0)
R.TELEMETRY_ADDR = s.getsockname()
if not R.push_telemetry():
    fail("push_telemetry 没发出去")
pkt = json.loads(s.recvfrom(8192)[0])
s.close()
if len(pkt.get("anchors") or []) != 8:
    fail("UDP 遥测锚点数不对")
if pkt.get("body") != "winch" or pkt.get("ball") is None:
    fail("UDP 遥测缺字段")

# 手动 jog：按住 200 mm/s，一帧应往 +X 走约 6.7 mm
bpy.data.objects["CMD_TARGET"].location = (-0.380, 0.520, 1.300)
bpy.context.view_layer.update()
x0 = bpy.data.objects["CMD_TARGET"].location.x
R.apply_intent({"intent": "jog", "v": [200.0, 0.0, 0.0]})
if tuple(R.JOG["v"]) != (200.0, 0.0, 0.0):
    fail("jog 没设置速度")
R._move_tick()
x1 = bpy.data.objects["CMD_TARGET"].location.x
if x1 <= x0 + 0.001:
    fail("jog 没让球移动：%.4f -> %.4f" % (x0, x1))

# stop 立即停
R.apply_intent({"intent": "stop"})
if any(R.JOG["v"]):
    fail("stop 没停手动 jog")

# 超时死手开关
R.apply_intent({"intent": "jog", "v": [200.0, 0.0, 0.0]})
R.JOG["t"] = time.monotonic() - 1.0
R._move_tick()
if any(R.JOG["v"]):
    fail("jog 超时没自己停")

# 贴左墙时不能再往左（安全层夹住）
bpy.data.objects["CMD_TARGET"].location = (-0.775, 0.520, 1.300)
bpy.context.view_layer.update()
R.apply_intent({"intent": "jog", "v": [-400.0, 0.0, 0.0]})
R._move_tick()
if bpy.data.objects["CMD_TARGET"].location.x * 1000.0 < -775.01:
    fail("jog 冲出了左墙")
R.apply_intent({"intent": "stop"})

print("PASS")
