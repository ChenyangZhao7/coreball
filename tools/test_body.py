import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import body  # noqa: E402

PTS = {
    "near": [-380.0, 520.0, 1300.0],
    "home": [-430.0, 760.0, 1420.0],
    "rover_near": [-450.0, 650.0, 0.0],
    "rover_home": [600.0, 250.0, 0.0],
}


def eq(a, b, msg):
    if a != b:
        raise SystemExit("FAIL: %s (%r != %r)" % (msg, a, b))


# 自由度
eq(body.supports("winch", "up"), True, "吊索能升降")
eq(body.supports("rover", "up"), False, "小车不能升降")
eq(body.supports("rover", "come"), True, "小车能过来")

# 拒绝要说清楚
r = body.map_intent("rover", "up", PTS, [0.0, 0.0, 0.0])
eq(r["kind"], "refuse", "小车升 -> refuse")
if "升降" not in r["reason"]:
    raise SystemExit("FAIL: 拒绝理由没写升降")

# 同一意图，两具身体去不同的点
eq(body.map_intent("winch", "come", PTS, [0, 0, 0])["point"], PTS["near"], "吊索 come")
eq(body.map_intent("rover", "come", PTS, [0, 0, 0])["point"], PTS["rover_near"], "小车 come")

# 相对位移：左 = −x，右 = +x（和 2D 地图、坐姿用户一致）
eq(body.map_intent("winch", "up", PTS, [0, 0, 1000])["point"], [0.0, 0.0, 1120.0], "吊索 up +120")
eq(body.map_intent("winch", "left", PTS, [0, 0, 0])["point"], [-120.0, 0.0, 0.0], "吊索 left −120")
eq(body.map_intent("winch", "right", PTS, [0, 0, 0])["point"], [120.0, 0.0, 0.0], "吊索 right +120")

# 脸窗在本地 +Y；Blender 绕 Z 正转把 +Y 转到 (−sin, cos)
eq(round(body.face_yaw(380.0, 370.0), 4), -0.7987, "脸朝向 +x/+y")
eq(round(body.face_yaw(-380.0, 370.0), 4), 0.7987, "脸朝向 −x/+y")

# 其他
eq(body.map_intent("winch", "look", PTS, [0, 0, 0])["kind"], "face", "look")
eq(body.map_intent("winch", "stop", PTS, [0, 0, 0])["kind"], "hold", "stop")
eq(body.map_intent("winch", "nope", PTS, [0, 0, 0]), None, "未知意图")
eq(body.map_intent("nobody", "come", PTS, [0, 0, 0]), None, "未知身体")

print("PASS")
