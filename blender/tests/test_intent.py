"""交互层无头验收。

用法：
  blender -b blender/out/cmd/coreball_command.blend --python-exit-code 1 --python blender/tests/test_intent.py
"""
import bpy
import sys
import os
import math
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))


def fail(msg):
    print("FAIL:", msg)
    sys.exit(1)


# ---------- Task 1：人与命名点 ----------
for name in ("PERSON_HEAD", "TGT_HOME", "TGT_NEAR"):
    if name not in bpy.data.objects:
        fail("场景里没有 %s" % name)

def near(vec, want, tol_mm=5.0):
    return (Vector(vec) - Vector(want)).length * 1000.0 <= tol_mm

if not near(bpy.data.objects["PERSON_HEAD"].matrix_world.translation, (0, 0.890, 1.250)):
    fail("PERSON_HEAD 位置不对：%s" % (bpy.data.objects["PERSON_HEAD"].matrix_world.translation,))
if not near(bpy.data.objects["TGT_NEAR"].matrix_world.translation, (-0.380, 0.520, 1.300), 1.0):
    fail("TGT_NEAR 位置不对")
if not near(bpy.data.objects["TGT_HOME"].matrix_world.translation, (-0.430, 0.760, 1.420), 1.0):
    fail("TGT_HOME 位置不对")


# ---------- Task 2：动作表 ----------
from cmd_runtime import load_actions, resolve, intent_point, ACTIONS_PATH
import tempfile

A = load_actions(ACTIONS_PATH)
if resolve(A, "key", "1") != "come":
    fail("按键 1 没映射到 come")
if resolve(A, "key", "9") is not None:
    fail("未知按键不该有映射")

pts = {"near": [-380.0, 520.0, 1300.0], "home": [-430.0, 760.0, 1420.0]}
if intent_point(A, "come", pts, [0, 0, 0]) != pts["near"]:
    fail("come 没解析到 near")
u = intent_point(A, "up", pts, [-100.0, 500.0, 1300.0])
if u != [-100.0, 500.0, 1420.0]:
    fail("up 的 delta 不对：%s" % (u,))
if intent_point(A, "nope", pts, [0, 0, 0]) is not None:
    fail("未知动作应返回 None")

bad = os.path.join(tempfile.gettempdir(), "bad_actions.json")
with open(bad, "w", encoding="utf-8") as f:
    f.write("{not json")
try:
    load_actions(bad)
    fail("坏动作表应该抛 ValueError")
except ValueError:
    pass


# ---------- Task 3：移动引擎 ----------
from cmd_runtime import move_profile, start_move, move_at

m = move_profile(1139.0, 356.0, 4.0)
if abs(m["T"] - 6.0) > 0.02:
    fail("1139mm 的时长不对：%.3f" % m["T"])

vmax, t, prev = 0.0, 0.0, m["pos"](0.0)
while t < 1.5 * m["T"]:
    t += 0.002
    cur = m["pos"](t)
    vmax = max(vmax, abs(cur - prev) / 0.002)
    prev = cur
if abs(vmax - 356.0) > 3.0:
    fail("峰值速度不对：%.1f" % vmax)
if abs(m["pos"](0.5) - 6.0) > 1.0:
    fail("前 0.5 秒走了 %.2f mm" % m["pos"](0.5))

over = max(m["pos"](t) - 1139.0 for t in [i * 0.01 for i in range(700)])
if not (2.5 <= over <= 5.5):
    fail("回弹不对：%.2f mm" % over)

t99 = next(i * 0.002 for i in range(1, 4000) if m["pos"](i * 0.002) >= 1139.0 * 0.99)
if abs(t99 - 5.38) > 0.12:
    fail("99%% 到位的时刻不对：%.2f" % t99)

style = {"vmax": 260.0, "hesitate": 0.35, "rebound": 4.0}
mv = start_move([0.0, 0.0, 0.0], [0.0, 0.0, 100.0], style, 10.0)
if move_at(mv, 10.20) != [0.0, 0.0, 0.0]:
    fail("犹豫期间就动了")
if move_at(mv, 10.85)[2] <= 1.0:
    fail("犹豫结束后没动")

# 移动途中被新指令覆盖：从当前位置重新起算，不跳变
mv2 = start_move(move_at(mv, 11.0), [0.0, 0.0, 300.0], style, 11.0)
if move_at(mv2, 11.0)[2] < 1.0:
    fail("新指令跳回了起点")


# ---------- Task 4：意图通道 ----------
from cmd_runtime import start_udp, route_intent
import socket
import queue
import time

s0 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s0.bind(("127.0.0.1", 0))
port = s0.getsockname()[1]
s0.close()

q = queue.Queue()
start_udp(port, q)
c = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
c.sendto(b'{"intent":"come","src":"test"}', ("127.0.0.1", port))
try:
    got = q.get(timeout=2)
except queue.Empty:
    fail("UDP 没收到意图")
if got.get("intent") != "come":
    fail("UDP 收到的内容不对：%s" % (got,))

c.sendto(b"not json", ("127.0.0.1", port))
time.sleep(0.2)
if not q.empty():
    fail("坏包进了队列")

r = route_intent(A, {"intent": "come"}, pts, [0.0, 0.0, 0.0])
if r["kind"] != "move" or r["point"] != pts["near"]:
    fail("come 没被解析成移动：%s" % (r,))
if r["style"].get("hesitate") != 0.35:
    fail("come 没带上 soft 风格")
if route_intent(A, {"intent": "nope"}, pts, [0.0, 0.0, 0.0])["kind"] != "unknown":
    fail("未知意图判错了")
if route_intent(A, {"intent": "stop"}, pts, [0.0, 0.0, 0.0])["kind"] != "hold":
    fail("stop 没判成 hold")
if route_intent(A, {"intent": "come", "conf": 0.1}, pts, [0.0, 0.0, 0.0])["kind"] != "ignored":
    fail("低置信度没被忽略")

# 屏幕控制：绝对点 + 表情
g = route_intent(A, {"intent": "goto", "point": [100, 300, 1200]}, pts, [0, 0, 0])
if g["kind"] != "move" or g["point"] != [100.0, 300.0, 1200.0]:
    fail("goto 没解析：%s" % (g,))
g = route_intent(A, {"intent": "goto", "point": [0, 890, 1300]}, pts, [0, 0, 0])
d = ((g["point"][0] ** 2 + (g["point"][1] - 890.0) ** 2) ** 0.5)
if d < 250.0 - 1e-3:
    fail("球心进了人的圆柱体：d=%.1f" % d)
g = route_intent(A, {"intent": "goto", "point": [100, 800, 1300]}, pts, [0, 0, 0])
d = ((g["point"][0] ** 2 + (g["point"][1] - 890.0) ** 2) ** 0.5)
if d < 250.0 - 1e-3:
    fail("斜向 goto 球心进了圆柱体：d=%.1f" % d)
g = route_intent(A, {"intent": "goto", "point": [2000, 1200, 1300]}, pts, [0, 0, 0])
if g["point"][:2] != [775.0, 1055.0]:
    fail("goto 没被墙夹紧：%s" % (g["point"],))
g = route_intent(A, {"intent": "right"}, pts, [775.0, 520.0, 1300.0])
if g["kind"] != "move" or g["point"][0] != 775.0:
    fail("右移没被墙夹紧：%s" % (g,))
g = route_intent(A, {"intent": "left"}, pts, [-775.0, 520.0, 1300.0])
if g["kind"] != "move" or g["point"][0] != -775.0:
    fail("左移没被墙夹紧：%s" % (g,))
if route_intent(A, {"intent": "goto", "point": [1, 2]}, pts, [0, 0, 0])["kind"] != "bad_target":
    fail("坏 goto 没拒绝")
if route_intent(A, {"intent": "expression", "name": "acting"}, pts, [0, 0, 0])["kind"] != "expression":
    fail("表情意图没识别")

from cmd_runtime import apply_intent, STATE as RSTATE
apply_intent({"intent": "nope"})
if RSTATE.get("last") != "不认识的指令":
    fail("未知意图没写进面板：%s" % (RSTATE.get("last"),))


# ---------- Task 5：朝向 / 表情 / 指令行 ----------
from cmd_runtime import face_person, set_expression, hud_lines as H

bpy.data.objects["CMD_TARGET"].location = (-0.380, 0.520, 1.300)
bpy.context.view_layer.update()
face_person()
yaw = bpy.data.objects["ball_root"].rotation_euler.z
fwd = Vector((-math.sin(yaw), math.cos(yaw), 0.0))
head = bpy.data.objects["PERSON_HEAD"].matrix_world.translation
ball = bpy.data.objects["CMD_TARGET"].matrix_world.translation
d = head - ball
d.z = 0.0
d.normalize()
if fwd.dot(d) < 0.99:
    fail("脸没对着人：yaw=%.3f" % yaw)

set_expression("acting")
b = bpy.data.materials["Pixel"].node_tree.nodes["Principled BSDF"]
if abs(b.inputs["Emission Strength"].default_value - 3.0) > 1e-4:
    fail("表情没切到 acting")
set_expression("idle")
if abs(b.inputs["Emission Strength"].default_value - 0.35) > 1e-4:
    fail("表情没回到 idle")

import tension as T
res = T.solve((-380.0, 520.0, 1460.0))
if "指令：come" not in "\n".join(H([0.0, 0.0, 1300.0], res, False, "come")):
    fail("面板没有指令行")

print("PASS")
