"""身体描述与意图映射：同一句指令，不同身体有不同的实现。

核心只发意图（come / look / stop ...），由这里决定这个身体能不能做、怎么做。
新增一个载体 = 在 BODIES 里加一项，不改核心。
"""
import math

BODIES = {
    "winch": {
        "class": 1,
        "name": "吊索",
        "axes": {"x": "mm", "y": "mm", "z": "mm"},
        "can": {"come", "back", "up", "down", "left", "right", "look", "stop"},
    },
    "rover": {
        "class": 3,
        "name": "小机器人",
        "axes": {"x": "mm", "y": "mm", "yaw": "deg"},
        "can": {"come", "back", "left", "right", "look", "stop"},
    },
}

ALL_INTENTS = {"come", "back", "up", "down", "left", "right", "look", "stop"}

REASONS = {
    "up": "这个身体没有升降",
    "down": "这个身体没有升降",
}

TARGETS = {
    "winch": {"come": "near", "back": "home"},
    "rover": {"come": "rover_near", "back": "rover_home"},
}


def supports(body, intent):
    return intent in (BODIES.get(body) or {}).get("can", set())


def face_yaw(dx, dy):
    """球脸窗在本地 +Y；Blender 绕 Z 正转把 +Y 转到 (−sin, cos)。

    dx / dy 是「目标点 → 人」的方向。返回值直接赋给 ball_root.rotation_euler.z。
    """
    return math.atan2(-dx, dy)


def map_intent(body, intent, points, current_mm):
    """返回 {kind: move/face/hold/refuse}。未知意图返回 None。"""
    if body not in BODIES:
        return None
    if intent in ALL_INTENTS and not supports(body, intent):
        return {"kind": "refuse", "reason": REASONS.get(intent, "这个身体做不到")}
    if intent not in ALL_INTENTS:
        return None

    if intent in ("come", "back"):
        name = TARGETS[body][intent]
        p = points.get(name)
        if p is None:
            return {"kind": "refuse", "reason": "找不到目标点 %s" % name}
        return {"kind": "move", "point": list(p)}

    if intent in ("up", "down"):
        dz = 120.0 if intent == "up" else -120.0
        return {"kind": "move", "point": [current_mm[0], current_mm[1], current_mm[2] + dz]}

    if intent in ("left", "right"):
        # 左 = −x，右 = +x：和 2D 地图、坐姿用户的左右一致
        dx = -120.0 if intent == "left" else 120.0
        return {"kind": "move", "point": [current_mm[0] + dx, current_mm[1], current_mm[2]]}

    if intent == "look":
        return {"kind": "face"}

    if intent == "stop":
        return {"kind": "hold"}

    return None
