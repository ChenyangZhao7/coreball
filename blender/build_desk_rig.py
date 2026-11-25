"""
CoreBall - 桌面五线吊装（含四个承力绞盘 + 供电张紧器）

四根承力线从四角绞盘的 200mm 横臂末端出去；
第五根是供电线，弹簧恒力盘在正上方，绕过吊点小滑轮往返。
几何上第五根永远落在四根线围成的锥体内部。

用法：
  blender --background --python build_desk_rig.py -- --out blender/out/rig --render
"""

import bpy
import sys
import os
import math
from math import sin, cos, pi, radians, sqrt, atan2
from mathutils import Vector

# ============================================================
# 参数（mm）
# ============================================================
WALL_H  = 1900
WALL_T  = 20
BOOTH_W = 1640
BOOTH_D = 1100
AX      = BOOTH_W / 2

DESK_W, DESK_D = 1560, 700
DESK_Z  = 740
DESK_T  = 25
DESK_CY = 370

BALL_POS = (-380, 520, 1300)   # 侧上方，距眼约 640mm
HUB_GAP  = 160

ANCHOR_IN = 120
ANCHOR_Z  = WALL_H - 150

BOOM_Z   = 1868
TETHER_Y = 520

CABLE_D  = 3.0
WIRE_D   = 2.0

MM = 0.001
HERE = os.path.dirname(os.path.abspath(__file__)) if "__file__" in dir() else os.getcwd()
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "tools"))
import interface_spec as I  # noqa: E402

# ============================================================
# 工具
# ============================================================
def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.unit_settings.system = 'METRIC'
    sc.unit_settings.length_unit = 'MILLIMETERS'
    sc.render.engine = 'BLENDER_EEVEE_NEXT'
    sc.render.resolution_x = 1800
    sc.render.resolution_y = 1350


def collection(name):
    c = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(c)
    return c


def _link(ob, coll):
    for c in list(ob.users_collection):
        c.objects.unlink(ob)
    coll.objects.link(ob)


def material(name, color, metallic=0.0, roughness=0.5, emission=None, strength=1.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*color, 1.0)
    b.inputs["Metallic"].default_value = metallic
    b.inputs["Roughness"].default_value = roughness
    if emission is not None:
        b.inputs["Emission Color"].default_value = (*emission, 1.0)
        b.inputs["Emission Strength"].default_value = strength
    return m


# 局部坐标 -> 世界坐标（用于把绞盘摆到四角并转向）
XF = {"loc": Vector((0, 0, 0)), "yaw": 0.0}

def T(p):
    v = Vector(p)
    if XF["yaw"]:
        c, s = cos(XF["yaw"]), sin(XF["yaw"])
        v = Vector((v.x * c - v.y * s, v.x * s + v.y * c, v.z))
    return v + XF["loc"]

def TD(d):
    d = Vector(d)
    if XF["yaw"]:
        c, s = cos(XF["yaw"]), sin(XF["yaw"])
        d = Vector((d.x * c - d.y * s, d.x * s + d.y * c, d.z))
    return d

def SET_XF(loc=(0, 0, 0), yaw=0.0):
    XF["loc"] = Vector(loc)
    XF["yaw"] = yaw


def box(name, center, size, mat, coll, bevel=0.0):
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=T(center) * MM)
    ob = bpy.context.object
    ob.name = name
    ob.scale = Vector(size) * MM
    if XF["yaw"]:
        ob.rotation_euler = (0, 0, XF["yaw"])
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    if mat:
        ob.data.materials.append(mat)
    if bevel > 0:
        m = ob.modifiers.new("bev", 'BEVEL')
        m.width = bevel * MM
        m.segments = 2
    _link(ob, coll)
    return ob


def cyl(name, center, radius, depth, mat, coll, direction=(0, 0, 1), verts=32):
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=verts, radius=radius * MM, depth=depth * MM,
        location=T(center) * MM)
    ob = bpy.context.object
    ob.name = name
    ob.rotation_mode = 'QUATERNION'
    ob.rotation_quaternion = TD(direction).normalized().to_track_quat('Z', 'Y')
    if mat:
        ob.data.materials.append(mat)
    _link(ob, coll)
    return ob


def sphere(name, center, radius, mat, coll, scale=(1, 1, 1), seg=32, rings=16):
    bpy.ops.mesh.primitive_uv_sphere_add(
        segments=seg, ring_count=rings, radius=radius * MM,
        location=T(center) * MM)
    ob = bpy.context.object
    ob.name = name
    ob.scale = Vector(scale)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    if mat:
        ob.data.materials.append(mat)
    for p in ob.data.polygons:
        p.use_smooth = True
    _link(ob, coll)
    return ob


def torus(name, center, major, minor, mat, coll, direction=(0, 0, 1), seg=48, mseg=10):
    verts, faces, idx = [], [], []
    for i in range(seg):
        t = 2 * pi * i / seg
        ring = []
        for j in range(mseg):
            p = 2 * pi * j / mseg
            rr = major + minor * cos(p)
            ring.append(len(verts))
            verts.append((rr * cos(t), rr * sin(t), minor * sin(p)))
        idx.append(ring)
    for i in range(seg):
        i2 = (i + 1) % seg
        for j in range(mseg):
            j2 = (j + 1) % mseg
            faces.append((idx[i][j], idx[i2][j], idx[i2][j2], idx[i][j2]))
    me = bpy.data.meshes.new(name)
    me.from_pydata([Vector(v) * MM for v in verts], [], faces)
    me.validate()
    ob = bpy.data.objects.new(name, me)
    coll.objects.link(ob)
    if mat:
        ob.data.materials.append(mat)
    for p in me.polygons:
        p.use_smooth = True
    ob.location = T(center) * MM
    ob.rotation_mode = 'QUATERNION'
    ob.rotation_quaternion = TD(direction).normalized().to_track_quat('Z', 'Y')
    return ob


def line(name, p1, p2, radius, mat, coll):
    cu = bpy.data.curves.new(name, 'CURVE')
    cu.dimensions = '3D'
    cu.bevel_depth = radius * MM
    cu.bevel_resolution = 2
    sp = cu.splines.new('POLY')
    sp.points.add(1)
    sp.points[0].co = (*T(p1) * MM, 1.0)
    sp.points[1].co = (*T(p2) * MM, 1.0)
    ob = bpy.data.objects.new(name, cu)
    ob.data.materials.append(mat)
    coll.objects.link(ob)
    return ob


# ============================================================
# 场景
# ============================================================
reset()

C_WALL  = collection("00_围板")
C_DESK  = collection("01_桌")
C_WINCH = collection("02_绞盘")
C_CABLE = collection("03_线缆")
C_HUB   = collection("04_吊点")
C_BALL  = collection("05_球")
C_LIGHT = collection("06_灯光相机")
C_PERSON = collection("08_人")

M_WALL  = material("Wall", (0.84, 0.85, 0.86), 0.0, 0.52)
M_FRAME = material("Frame", (0.17, 0.18, 0.20), 0.55, 0.40)
M_MOTOR = material("Motor", (0.07, 0.075, 0.085), 0.35, 0.45)
M_ALLOY = material("Alloy", (0.70, 0.72, 0.75), 0.92, 0.26)
M_STEEL = material("Steel", (0.85, 0.86, 0.88), 0.98, 0.16)
M_CABLE = material("Dyneema", (0.90, 0.91, 0.92), 0.0, 0.28)
M_WIRE  = material("Wire", (0.10, 0.10, 0.12), 0.1, 0.55)
M_SPRING= material("Spring", (0.62, 0.64, 0.68), 0.95, 0.20)
M_RING  = material("SlipRing", (0.80, 0.62, 0.30), 0.95, 0.22)
M_MAG   = material("Magnet", (0.86, 0.72, 0.42), 0.95, 0.20)
M_DESK  = material("Desk", (0.38, 0.30, 0.23), 0.0, 0.65)
M_SCREEN= material("Screen", (0.02, 0.03, 0.05), 0.0, 0.20,
                   emission=(0.12, 0.19, 0.30), strength=0.9)
M_FLOOR = material("Floor", (0.05, 0.055, 0.06), 0.0, 0.85)
M_SKIN  = material("Skin", (0.72, 0.55, 0.43), 0.0, 0.55)
M_SHIRT = material("Shirt", (0.26, 0.36, 0.46), 0.0, 0.70)
M_PANTS = material("Pants", (0.16, 0.18, 0.22), 0.0, 0.75)
M_HAIR  = material("Hair", (0.08, 0.07, 0.06), 0.0, 0.55)
M_SHOE  = material("Shoe", (0.08, 0.08, 0.10), 0.2, 0.50)
M_CHAIR = material("Chair", (0.11, 0.12, 0.14), 0.2, 0.50)

# ---------------- 围板 ----------------
box("floor", (0, 1300, -10), (5000, 5000, 20), M_FLOOR, C_WALL)
box("wall_back", (0, 0, WALL_H / 2), (BOOTH_W + 2 * WALL_T, WALL_T, WALL_H), M_WALL, C_WALL)
for sx in (-1, 1):
    box(f"wall_side_{sx}", (sx * AX, BOOTH_D / 2, WALL_H / 2),
        (WALL_T, BOOTH_D, WALL_H), M_WALL, C_WALL)
for sx in (-1, 1):
    for y in (0, BOOTH_D):
        box(f"edge_{sx}_{y}", (sx * AX, y, WALL_H / 2), (36, 36, WALL_H), M_FRAME, C_WALL)
box("edge_top_back", (0, 0, WALL_H), (BOOTH_W + 2 * WALL_T, 36, 36), M_FRAME, C_WALL)
for sx in (-1, 1):
    box(f"edge_top_{sx}", (sx * AX, BOOTH_D / 2, WALL_H), (36, BOOTH_D, 36), M_FRAME, C_WALL)

# ---------------- 桌 ----------------
box("desk", (0, DESK_CY, DESK_Z - DESK_T / 2), (DESK_W, DESK_D, DESK_T), M_DESK, C_DESK, bevel=4)
for sx in (-1, 1):
    for ly in (-1, 1):
        box(f"leg_{sx}_{ly}", (sx * (DESK_W / 2 - 70), DESK_CY + ly * (DESK_D / 2 - 70),
             (DESK_Z - DESK_T) / 2), (46, 46, DESK_Z - DESK_T), M_FRAME, C_DESK)
box("monitor", (0, 190, DESK_Z + 200), (620, 26, 360), M_MOTOR, C_DESK, bevel=3)
box("monitor_scr", (0, 205, DESK_Z + 200), (596, 2, 336), M_SCREEN, C_DESK)

# ---------------- 三面墙承力绞盘（墙平面出线）----------------
DRUM_Z = 45.0
ARM_X  = 205.0
SHEAVE_R = 17.0
SH_Z = 116.0       # 出线滑轮抬高 120 mm，在墙平面

# (壁板中心, yaw, 沿墙臂的方向 ±1, 滑轮向房间内的偏移 mm)
CORNERS = [
    ((-555.0,  12.0, 1750.0), 0.0, -1, 0),          # 后墙左
    (( 808.0, 895.0, 1661.0), radians(90),  1, 28),  # 右墙前角，内移 28
    ((-95.0,   12.0, 1750.0), 0.0, -1, 0),          # 后墙中
    ((-808.0, 895.0, 1661.0), radians(-90), -1, 28), # 左墙前角，内移 28
    (( 555.0,  12.0, 1571.0), 0.0,  1, 0),          # 后墙右
    ((-808.0, 405.0, 1750.0), radians(-90),  1, 0),  # 左墙中
    (( 808.0, 295.0, 1661.0), radians(90),  1, 0),  # 右墙中
    (( 808.0, 595.0, 1661.0), radians(90),  1, 0),  # 右墙中
]
CENTER = Vector((0, BOOTH_D * 0.5, 0))

def build_winch(idx, corner, yaw, arm_dir, fair_in):
    SET_XF((corner[0], corner[1], corner[2]), yaw)
    t = f"W{idx}_"
    # 壁板（贴墙，不再需要转角填块）
    box(t + "plate", (0, 0, 0), (112, 8, 250), M_FRAME, C_WINCH, bevel=2)
    # 电机（竖直）+ 编码器
    box(t + "motor", (0, 0, 96), (42.3, 42.3, 48), M_MOTOR, C_WINCH, bevel=2)
    box(t + "motor_mount", (0, 0, 128), (54, 54, 10), M_FRAME, C_WINCH, bevel=2)
    cyl(t + "encoder", (0, 0, 135), 9, 3, M_MOTOR, C_WINCH, verts=32)
    cyl(t + "coupling", (0, 0, 66), 9, 16, M_ALLOY, C_WINCH, verts=24)
    # 卷筒
    cyl(t + "drum", (0, 0, DRUM_Z), 17, 26, M_ALLOY, C_WINCH, verts=48)
    for zz in (DRUM_Z - 13, DRUM_Z + 13):
        cyl(t + f"flange_{int(zz)}", (0, 0, zz), 22, 2, M_ALLOY, C_WINCH, verts=48)
    box(t + "bearing", (0, 0, 14), (50, 50, 20), M_FRAME, C_WINCH, bevel=2)
    # 前角滑轮向房间内让开前立柱；用垫块把斜撑接回壁板
    fy = float(fair_in)
    if fy > 0:
        box(t + "spacer", (0, fy / 2, 22), (30, fy + 6, 14), M_FRAME, C_WINCH, bevel=1)
    # 沿墙斜撑 205 mm，把出线滑轮送到墙平面
    ax = arm_dir * ARM_X
    strut_len = math.hypot(ARM_X, SH_Z - 22.0)
    cyl(t + "strut", (ax / 2, fy, (SH_Z + 22.0) / 2), 7, strut_len,
        M_FRAME, C_WINCH, direction=(ax, 0, SH_Z - 22.0), verts=16)
    # 出线滑轮（轴沿 Y，滑轮在墙平面，暴露）
    for yy in (-18.0, 18.0):
        box(t + f"cheek_{int(yy)}", (ax, fy + yy, SH_Z + 4), (44, 5, 38),
            M_FRAME, C_WINCH, bevel=1)
    cyl(t + "sheave", (ax, fy, SH_Z), SHEAVE_R, 12, M_STEEL, C_WINCH,
        direction=(0, 1, 0), verts=44)
    pin_half = 17.0 if fy > 0 else 30.0
    cyl(t + "loadpin", (ax, fy, SH_Z), 4, 2 * pin_half + 6, M_ALLOY, C_WINCH,
        direction=(0, 1, 0), verts=20)
    for yy in (-pin_half, pin_half):
        cyl(t + f"pincap_{int(yy)}", (ax, fy + yy, SH_Z), 9, 8, M_MOTOR, C_WINCH,
            direction=(0, 1, 0), verts=24)
    return T((ax, fy, SH_Z - SHEAVE_R))

exit_pts = []
for i, c in enumerate(CORNERS, 1):
    exit_pts.append(build_winch(i, c[0], c[1], c[2], c[3]))

SET_XF()

# ---------------- 虚构人物：坐姿，约 185 cm / 80 kg 比例 ----------------
# 只做尺度和遮挡参考，不是真实人物；面朝桌子（-Y），坐在开口侧。
def limb(name, p1, p2, r, mat):
    p1, p2 = Vector(p1), Vector(p2)
    d = p2 - p1
    return cyl(name, (p1 + p2) / 2, r, d.length, mat, C_PERSON,
               direction=d, verts=20)

# 椅子
box("chair_seat", (0, 940, 450), (460, 440, 30), M_CHAIR, C_PERSON, bevel=8)
box("chair_back", (0, 1030, 760), (460, 30, 460), M_CHAIR, C_PERSON, bevel=8)
for sx in (-190, 190):
    for sy in (820, 1040):
        box(f"chair_leg_{sx}_{sy}", (sx, sy, 225), (30, 30, 450),
            M_CHAIR, C_PERSON, bevel=5)

# 骨盆 / 躯干 / 肩
box("person_pelvis", (0, 940, 520), (340, 230, 170), M_PANTS, C_PERSON, bevel=28)
box("person_torso", (0, 940, 800), (420, 230, 520), M_SHIRT, C_PERSON, bevel=48)
for sx in (-190, 190):
    sphere(f"person_shoulder_{sx}", (sx, 940, 1020), 72, M_SHIRT, C_PERSON,
           scale=(1.0, 0.9, 0.9))

# 手臂：肩 -> 肘 -> 手（手放在桌面上）
for sx in (-1, 1):
    sh = (sx * 200, 940, 1010)
    el = (sx * 235, 760, 810)
    ha = (sx * 260, 560, 748)
    limb(f"person_upper_arm_{sx}", sh, el, 45, M_SHIRT)
    limb(f"person_forearm_{sx}", el, ha, 38, M_SHIRT)
    sphere(f"person_hand_{sx}", ha, 42, M_SKIN, C_PERSON)

# 腿：髋 -> 膝 -> 踝，脚在地面
for sx in (-1, 1):
    hip = (sx * 105, 940, 510)
    knee = (sx * 105, 600, 490)
    ankle = (sx * 105, 540, 100)
    limb(f"person_thigh_{sx}", hip, knee, 75, M_PANTS)
    limb(f"person_shin_{sx}", knee, ankle, 55, M_PANTS)
    box(f"person_foot_{sx}", (sx * 105, 500, 45), (90, 230, 70),
        M_SHOE, C_PERSON, bevel=10)

# 脖子 / 头 / 头发
cyl("person_neck", (0, 900, 1100), 58, 130, M_SKIN, C_PERSON, verts=32)
sphere("person_head", (0, 890, 1250), 95, M_SKIN, C_PERSON,
       scale=(0.85, 0.92, 1.02), seg=40, rings=24)
sphere("person_hair", (0, 905, 1290), 94, M_HAIR, C_PERSON,
       scale=(0.84, 0.92, 0.62), seg=40, rings=20)
sphere("person_hair_back", (0, 940, 1240), 86, M_HAIR, C_PERSON,
       scale=(0.80, 0.50, 0.80), seg=32, rings=16)
for sx in (-1, 1):
    sphere(f"person_ear_{sx}", (sx * 82, 890, 1250), 16, M_SKIN, C_PERSON,
           scale=(0.6, 0.8, 1.0), seg=20, rings=12)
    sphere(f"person_eye_{sx}", (sx * 32, 808, 1270), 9, M_MOTOR, C_PERSON,
           seg=16, rings=10)
sphere("person_nose", (0, 800, 1240), 11, M_SKIN, C_PERSON, seg=16, rings=10)
box("person_mouth", (0, 808, 1205), (46, 6, 6), M_MOTOR, C_PERSON, bevel=2)

# ---------------- 吊点 ----------------
hub = Vector((BALL_POS[0], BALL_POS[1], BALL_POS[2] + HUB_GAP))

cyl("hub_plate", hub, 46, 10, M_FRAME, C_HUB, verts=56)
cyl("hub_cap", hub + Vector((0, 0, 7)), 20, 6, M_ALLOY, C_HUB, verts=40)

lugs = []
for i, a in enumerate(exit_pts, 1):
    d = a - hub
    d.z = 0
    d.normalize()
    lug = hub + d * 30 + Vector((0, 0, -2))
    lugs.append(lug)
    cyl(f"lug_{i}", lug, 5, 18, M_STEEL, C_HUB, direction=d, verts=16)

# ---------------- 下方：竖直导轨 + 偏航 + 滑环 ----------------
# 竖直行程 ±45mm（合计 90），当前在中位
RAIL_TOP = hub.z - 8.0
RAIL_LEN = 110.0
CARRIAGE_Z = RAIL_TOP - 55.0

for sx in (-25.0, 25.0):
    box(f"hub_rail_{int(sx)}", (hub.x + sx, hub.y, RAIL_TOP - RAIL_LEN / 2),
        (10, 16, RAIL_LEN), M_ALLOY, C_HUB, bevel=2)
cyl("hub_screw", (hub.x, hub.y, RAIL_TOP - RAIL_LEN / 2), 3.2, RAIL_LEN,
    M_MOTOR, C_HUB, verts=20)
box("hub_carriage", (hub.x, hub.y, CARRIAGE_Z), (60, 44, 26), M_FRAME, C_HUB, bevel=3)

# 偏航转轴 + 滑环
cyl("hub_yaw", (hub.x, hub.y, CARRIAGE_Z - 20), 17, 16, M_ALLOY, C_HUB, verts=40)
cyl("hub_yaw_ring", (hub.x, hub.y, CARRIAGE_Z - 29), 19, 4, M_STEEL, C_HUB, verts=48)
cyl("hub_slipring", (hub.x, hub.y, CARRIAGE_Z - 38), 9, 10, M_MOTOR, C_HUB, verts=28)
for k in range(4):
    torus(f"hub_slipring_ring_{k}", (hub.x, hub.y, CARRIAGE_Z - 35 - k * 2.2),
          9.4, 0.6, M_RING, C_HUB, seg=32, mseg=6)

# 插头（接口 v1.0：鼻子插进井里，肩部坐在球面上）
BALL_TOP = BALL_POS[2] + I.BALL_R   # 1340，真实球顶（不能用 plug_z-6，会低 1mm）
plug_z = BALL_TOP + 6               # 肩部中心，跨 BALL_TOP .. BALL_TOP+12
PLUG_END = BALL_TOP - I.PLUG_H      # 鼻子端面，井底上方 0.4

# 鼻子：φ29.6 × 4.6，顶面齐平球顶
cyl("hub_plug", (hub.x, hub.y, BALL_TOP - I.PLUG_H / 2), I.PLUG_R, I.PLUG_H,
    M_ALLOY, C_HUB, verts=40)
# 肩部：φ34 × 12
cyl("hub_plug_body", (hub.x, hub.y, plug_z), 17, 12, M_ALLOY, C_HUB, verts=48)

# 键（不等距，只有一种插法）：从端面往井里伸
for k, ang in enumerate(I.KEY_ANGLES):
    dx, dy = I.polar(I.KEY_R, ang)
    box(f"plug_key_{k}", (hub.x + dx, hub.y + dy, PLUG_END - I.KEY_H / 2),
        (I.KEY_W, I.KEY_W, I.KEY_H), M_MOTOR, C_HUB, bevel=0.3)

# 磁铁：嵌在鼻子端面，底面齐平
for k, ang in enumerate(I.MAGNET_ANGLES):
    dx, dy = I.polar(I.MAGNET_R, ang)
    cyl(f"plug_magnet_{k}", (hub.x + dx, hub.y + dy, PLUG_END + I.MAGNET_H / 2),
        I.MAGNET_D / 2, I.MAGNET_H, M_MAG, C_HUB, verts=24)

# 触点针：GND 最长（先接地）、VBUS 最短
# 长度是未压缩的 pogo 行程，插入后压回。本场景导入的是真实球（有井、焊盘、键槽），
# 针按未压缩长度画出，所以端面会压到焊盘/井底上方——这是示意画法，不是球实心导致穿模
PIN_LEN = {"GND": 1.8, "TX": 1.3, "RX": 1.3, "VBUS": 0.8}
for k, ang in enumerate(I.pad_angles(4)):
    dx, dy = I.polar(I.PAD_PITCH_R, ang)
    L = PIN_LEN[I.PIN_NAMES[k]]
    cyl(f"plug_pin_{k}", (hub.x + dx, hub.y + dy, PLUG_END - L / 2),
        0.75, L, M_STEEL, C_HUB, verts=12)

# 摩擦环：O 圈坐在井壁圆柱段内（井壁 35.0–37.08；环心 36.0，避免落到井口以上）
torus("friction_ring", (hub.x, hub.y, PLUG_END + 0.6),
      I.FRICTION_R, I.FRICTION_D / 2, M_MOTOR, C_HUB, seg=64, mseg=8)

# 磁吸脱开环：外移到肩部之外才看得见（φ34 肩会盖住旧的 14.5/1.8）
torus("breakaway_ring", (hub.x, hub.y, BALL_TOP), 18.2, 0.8, M_STEEL, C_HUB,
      seg=64, mseg=8)

# 吊点顶部的小滑轮（供电线绕它往返）
tether_pulley = hub + Vector((0, 0, 46))
box("tether_yoke", (hub.x, hub.y, tether_pulley.z - 16), (18, 34, 22), M_FRAME, C_HUB, bevel=2)
cyl("tether_sheave", tether_pulley, 16, 10, M_STEEL, C_HUB, direction=(1, 0, 0), verts=40)
cyl("tether_axle", tether_pulley, 3.5, 34, M_ALLOY, C_HUB, direction=(1, 0, 0), verts=16)

# ---------------- 四根承力线 ----------------
cable_len = []
for i, (a, lug) in enumerate(zip(exit_pts, lugs), 1):
    line(f"cable_{i}", a, lug, CABLE_D / 2, M_CABLE, C_CABLE)
    cable_len.append((a - lug).length)

# ---------------- 第五根：供电张紧器 ----------------
box("boom", (0, TETHER_Y / 2, BOOM_Z), (34, TETHER_Y, 34), M_FRAME, C_WINCH, bevel=1.5)
box("boom_brace", (0, 24, BOOM_Z - 170), (24, 24, 24), M_FRAME, C_WINCH)
box("reel_plate", (0, TETHER_Y, BOOM_Z - 10), (200, 118, 8), M_FRAME, C_WINCH, bevel=2)
# 弹簧恒力盘
cyl("reel_house", (0, TETHER_Y - 50, BOOM_Z - 34), 32, 20, M_MOTOR, C_WINCH,
    direction=(0, 1, 0), verts=48)
cyl("reel_drum", (0, TETHER_Y - 50, BOOM_Z - 34), 25, 12, M_ALLOY, C_WINCH,
    direction=(0, 1, 0), verts=48)
torus("reel_spring", (0, TETHER_Y - 50, BOOM_Z - 34), 16, 2.4, M_SPRING, C_WINCH,
      direction=(0, 1, 0), seg=48, mseg=8)
# 转向滑轮
for xx in (-15.0, 15.0):
    box(f"reel_cheek_{int(xx)}", (xx, TETHER_Y, BOOM_Z - 48), (5, 40, 46),
        M_FRAME, C_WINCH, bevel=1)
cyl("reel_sheave", (0, TETHER_Y, BOOM_Z - 52), 16, 10, M_STEEL, C_WINCH,
    direction=(1, 0, 0), verts=44)
# 固定锚点
box("reel_anchor", (0, TETHER_Y + 76, BOOM_Z - 34), (26, 26, 22), M_ALLOY,
    C_WINCH, bevel=2)
torus("reel_eye", (0, TETHER_Y + 76, BOOM_Z - 52), 6, 2.4, M_STEEL, C_WINCH,
      direction=(0, 1, 0), seg=24, mseg=8)

# 两股线
w1 = Vector((0, TETHER_Y - 50, BOOM_Z - 44))
w2 = Vector((0, TETHER_Y + 76, BOOM_Z - 58))
line("wire_1", w1, tether_pulley, WIRE_D / 2, M_WIRE, C_CABLE)
line("wire_2", tether_pulley, w2, WIRE_D / 2, M_WIRE, C_CABLE)

# ---------------- 球 ----------------
BALL_BLEND = os.path.join(HERE, "out", "ball", "coreball_ball.blend")
ball_root = bpy.data.objects.new("ball_root", None)
C_BALL.objects.link(ball_root)
ball_root.location = Vector(BALL_POS) * MM

if os.path.exists(BALL_BLEND):
    PREFIX = ("shell_", "window_", "px_", "if_", "ir_port",
              "vent_", "usb_", "reset_", "status_", "power_", "spk_",
              "battery", "pcb_", "speaker", "mic_")
    with bpy.data.libraries.load(BALL_BLEND, link=False) as (src, dst):
        dst.objects = [n for n in src.objects if n.startswith(PREFIX)]
    for ob in dst.objects:
        if ob is None:
            continue
        C_BALL.objects.link(ob)
        ob.parent = ball_root
        ob.matrix_parent_inverse = ball_root.matrix_world.inverted()
    print("appended ball objects:", len(dst.objects))

# ============================================================
# 灯光 / 相机
# ============================================================
world = bpy.data.worlds.new("World")
bpy.context.scene.world = world
world.use_nodes = True
world.node_tree.nodes["Background"].inputs[0].default_value = (0.02, 0.024, 0.031, 1.0)
world.node_tree.nodes["Background"].inputs[1].default_value = 1.0

aim = Vector((0, 500, 1150))

def area(name, loc, energy, size, color):
    d = bpy.data.lights.new(name, 'AREA')
    d.energy = energy
    d.size = size * MM
    d.color = color
    ob = bpy.data.objects.new(name, d)
    ob.location = Vector(loc) * MM
    C_LIGHT.objects.link(ob)
    e = bpy.data.objects.new(f"aim_{name}", None)
    e.location = aim * MM
    C_LIGHT.objects.link(e)
    c = ob.constraints.new('TRACK_TO')
    c.target = e
    c.track_axis = 'TRACK_NEGATIVE_Z'
    c.up_axis = 'UP_Y'
    return ob

area("key",  (-1500, 2200, 2500), 120, 900, (1.0, 0.96, 0.90))
area("fill", (2000, 1500, 1600), 40, 700, (0.72, 0.84, 1.0))
area("rim",  (500, -1200, 2200), 55, 700, (0.55, 0.88, 1.0))
area("top",  (0, 700, 2600), 40, 900, (0.85, 0.90, 1.0))

cam_data = bpy.data.cameras.new("Cam")
cam_data.lens = 42
cam = bpy.data.objects.new("Cam", cam_data)
cam.location = Vector((900, 3400, 2200)) * MM
C_LIGHT.objects.link(cam)
bpy.context.scene.camera = cam
tgt = bpy.data.objects.new("CamTgt", None)
tgt.location = Vector((0, 500, 1050)) * MM
C_LIGHT.objects.link(tgt)
c = cam.constraints.new('TRACK_TO')
c.target = tgt
c.track_axis = 'TRACK_NEGATIVE_Z'
c.up_axis = 'UP_Y'

sc = bpy.context.scene
sc.use_nodes = True
tree = sc.node_tree
for n in list(tree.nodes):
    tree.nodes.remove(n)
rl = tree.nodes.new("CompositorNodeRLayers")
gl = tree.nodes.new("CompositorNodeGlare")
gl.glare_type = 'FOG_GLOW'
gl.quality = 'HIGH'
gl.threshold = 0.9
gl.size = 7
cp = tree.nodes.new("CompositorNodeComposite")
tree.links.new(rl.outputs["Image"], gl.inputs["Image"])
tree.links.new(gl.outputs["Image"], cp.inputs["Image"])

# ============================================================
# 输出
# ============================================================
argv = sys.argv
out_dir = os.path.join(HERE, "out", "rig")
do_render = False
if "--" in argv:
    rest = argv[argv.index("--") + 1:]
    if "--out" in rest:
        out_dir = rest[rest.index("--out") + 1]
    do_render = "--render" in rest

os.makedirs(out_dir, exist_ok=True)
bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(os.path.join(out_dir, "coreball_rig.blend")))

print("=" * 56)
print("八线长:", ", ".join("%.0f" % L for L in cable_len), "mm")
print("第五线:", "%.0f + %.0f mm（两股）" % ((w1 - tether_pulley).length, (w2 - tether_pulley).length))
print("绞盘臂尖:", [tuple(round(v) for v in p) for p in exit_pts])
print("=" * 56)

if do_render:
    def shoot(path, cam_loc, tgt_loc, lens, res=None):
        cam.location = Vector(cam_loc) * MM
        tgt.location = Vector(tgt_loc) * MM
        cam_data.lens = lens
        sc.render.resolution_x = res if res else 1800
        sc.render.resolution_y = res if res else 1350
        sc.render.filepath = os.path.abspath(os.path.join(out_dir, path))
        sc.render.image_settings.file_format = 'PNG'
        bpy.ops.render.render(write_still=True)
        print("shot:", path)

    shoot("rig_overview.png", (1000, 3300, 2300), (0, 500, 1050), 42)
    shoot("rig_front.png",    (0, 3300, 1400), (0, 500, 1100), 48)
    shoot("rig_side.png",     (3100, 1400, 1500), (0, 500, 1100), 48)
    shoot("rig_top.png",      (300, 1500, 3100), (0, 500, 900), 45)
    shoot("rig_hub.png",      (140, 1450, 1720), (-380, 520, 1350), 72, 1500)
    shoot("rig_corner.png",   (620, 980, 1180), (-700, 200, 1760), 60, 1500)
