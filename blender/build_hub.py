"""
CoreBall - 吊点总成 v2

新增两件事：
  1. 360° 偏航轴（含微型滑环，电从静态盘过到旋转体）
  2. 短行程伸缩轴（0–90mm），负责快速的小幅升降

分工：
  大范围 XYZ   → 四根承力线
  朝向         → 偏航轴
  快速小升降   → 伸缩轴

用法：
  blender --background --python build_hub.py -- --out blender/out/hub --render
"""

import bpy
import sys
import os
import math
from math import sin, cos, pi, radians, erf
from mathutils import Vector

MM = 0.001
HERE = os.path.dirname(os.path.abspath(__file__)) if "__file__" in dir() else os.getcwd()
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "tools"))
import interface_spec as I  # noqa: E402

# ---------------- 尺寸 ----------------
HUB_POS   = Vector((-380.0, 520.0, 1370.0))
ANCHORS = [Vector((-760.0, 12.0, 1849.0)), Vector((780.0, 1100.0, 1760.0)),
           Vector((-300.0, 12.0, 1849.0)), Vector((-780.0, 1100.0, 1760.0)),
           Vector((760.0, 12.0, 1670.0)), Vector((-808.0, 200.0, 1849.0)),
           Vector((808.0, 500.0, 1760.0)), Vector((808.0, 800.0, 1760.0))]

EXT_OUT   = 6.0       # 当前伸出量（行程 0–90）；默认收拢
for _a in sys.argv:
    if _a.startswith("--ext="):
        EXT_OUT = float(_a.split("=")[1])
TUBE_D    = 16.0

# ============================================================
def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.unit_settings.system = 'METRIC'
    sc.unit_settings.length_unit = 'MILLIMETERS'
    sc.render.engine = 'BLENDER_EEVEE_NEXT'
    sc.render.resolution_x = 1600
    sc.render.resolution_y = 1600


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


def box(name, center, size, mat, coll, bevel=0.0):
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=Vector(center) * MM)
    ob = bpy.context.object
    ob.name = name
    ob.scale = Vector(size) * MM
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    if mat:
        ob.data.materials.append(mat)
    if bevel > 0:
        m = ob.modifiers.new("bev", 'BEVEL')
        m.width = bevel * MM
        m.segments = 2
    _link(ob, coll)
    return ob


def cyl(name, center, radius, depth, mat, coll, direction=(0, 0, 1), verts=40):
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=verts, radius=radius * MM, depth=depth * MM,
        location=Vector(center) * MM)
    ob = bpy.context.object
    ob.name = name
    ob.rotation_mode = 'QUATERNION'
    ob.rotation_quaternion = Vector(direction).normalized().to_track_quat('Z', 'Y')
    if mat:
        ob.data.materials.append(mat)
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
    ob.location = Vector(center) * MM
    ob.rotation_mode = 'QUATERNION'
    ob.rotation_quaternion = Vector(direction).normalized().to_track_quat('Z', 'Y')
    return ob


def rod(name, p1, p2, r, mat, coll):
    p1, p2 = Vector(p1), Vector(p2)
    d = p2 - p1
    return cyl(name, (p1 + p2) / 2, r, d.length, mat, coll, direction=d, verts=12)


# ============================================================
reset()

C_STATIC = collection("00_静态")
C_YAW    = collection("01_偏航")
C_SLIDE  = collection("02_伸缩")
C_BALL   = collection("03_球")
C_LIGHT  = collection("04_灯光相机")

M_FRAME = material("Frame", (0.16, 0.17, 0.19), 0.55, 0.40)
M_MOTOR = material("Motor", (0.07, 0.075, 0.085), 0.35, 0.45)
M_ALLOY = material("Alloy", (0.72, 0.74, 0.77), 0.92, 0.24)
M_STEEL = material("Steel", (0.85, 0.86, 0.88), 0.98, 0.16)
M_MAG   = material("Magnet", (0.86, 0.72, 0.42), 0.95, 0.20)
M_RING  = material("SlipRing", (0.80, 0.62, 0.30), 0.95, 0.22)
M_WIRE  = material("Wire", (0.10, 0.10, 0.12), 0.1, 0.55)
M_SHELL = material("Shell", (0.93, 0.935, 0.94), 0.02, 0.30)
M_GLASS = material("Glass", (0.015, 0.02, 0.03), 0.15, 0.10)
M_FLOOR = material("Floor", (0.05, 0.055, 0.06), 0.0, 0.85)

H = HUB_POS

# ---------------- 静态：挂耳 + 顶盘 + 供电滑轮 ----------------
cyl("hub_top_plate", H, 32, 7, M_FRAME, C_STATIC, verts=56)
cyl("hub_top_cap", H + Vector((0, 0, 5)), 20, 5, M_ALLOY, C_STATIC, verts=48)

# 四根线的挂耳（朝向各自的锚点）
for i, A in enumerate(ANCHORS, 1):
    d = A - H
    d.z = 0
    d.normalize()
    lug = H + d * 30 + Vector((0, 0, -1))
    cyl(f"lug_{i}", lug, 5, 18, M_STEEL, C_STATIC, direction=d, verts=16)

# 供电的小滑轮（在顶上，线绕它往返）
PUL = H + Vector((0, 0, 30))
box("tether_yoke", (H.x, H.y, PUL.z - 13), (18, 34, 20), M_FRAME, C_STATIC, bevel=2)
cyl("tether_sheave", PUL, 15, 10, M_STEEL, C_STATIC, direction=(1, 0, 0), verts=40)
cyl("tether_axle", PUL, 3.5, 34, M_ALLOY, C_STATIC, direction=(1, 0, 0), verts=16)

# ---------------- 滑环（电从静态到旋转体）----------------
cyl("slipring_body", H + Vector((0, 0, -11)), 9, 14, M_MOTOR, C_STATIC, verts=36)
for k in range(4):
    torus(f"slipring_ring_{k}", H + Vector((0, 0, -6 - k * 3.2)), 9.4, 0.7,
          M_RING, C_STATIC, seg=36, mseg=6)

# ---------------- 偏航：轴承 + 电机 + 齿轮 ----------------
cyl("yaw_bearing", H + Vector((0, 0, -21)), 17, 6, M_STEEL, C_STATIC, verts=48)
box("yaw_motor", (H.x + 19, H.y, H.z - 21), (28, 28, 26), M_MOTOR, C_YAW, bevel=2)
cyl("yaw_pinion", (H.x + 8.5, H.y, H.z - 21), 5.5, 7, M_ALLOY, C_YAW, verts=24)
cyl("yaw_gear", (H.x, H.y, H.z - 26), 15, 5, M_ALLOY, C_YAW, verts=48)

# 旋转盘
cyl("yaw_plate", H + Vector((0, 0, -31)), 26, 6, M_FRAME, C_YAW, verts=48)

# ---------------- 伸缩：外管 + 内管 + 丝杠 ----------------
TOP = H.z - 34
cyl("slide_outer", (H.x, H.y, TOP - 20), TUBE_D / 2, 40, M_ALLOY, C_SLIDE, verts=36)
cyl("slide_collar", (H.x, H.y, TOP - 40), 10, 6, M_FRAME, C_SLIDE, verts=36)
cyl("slide_inner", (H.x, H.y, TOP - 40 - EXT_OUT / 2), 5.5, EXT_OUT + 6,
    M_STEEL, C_SLIDE, verts=28)
# 丝杠（示意，藏在管里）
cyl("slide_screw", (H.x, H.y, TOP - 18), 2.4, 40, M_MOTOR, C_SLIDE, verts=16)

# 底部插头 + 磁环（接口 v1.0：鼻子插进井里，肩部坐在球面上）
BOT = TOP - 40 - EXT_OUT
BALL_TOP = BOT - 14              # 球顶平面（球心 BOT-54，半径 40）
PLUG_END = BALL_TOP - I.PLUG_H   # 鼻子端面

# 鼻子：φ29.6 × 4.6，顶面齐平球顶
cyl("hub_plug", (H.x, H.y, BALL_TOP - I.PLUG_H / 2), I.PLUG_R, I.PLUG_H,
    M_ALLOY, C_SLIDE, verts=40)
# 肩部：φ34 × 12，坐在球面之上
cyl("hub_plug_body", (H.x, H.y, BALL_TOP + 6), 17, 12, M_ALLOY, C_SLIDE, verts=48)

# 键（不等距，只有一种插法）：从端面往井里伸
for k, ang in enumerate(I.KEY_ANGLES):
    dx, dy = I.polar(I.KEY_R, ang)
    box(f"plug_key_{k}", (H.x + dx, H.y + dy, PLUG_END - I.KEY_H / 2),
        (I.KEY_W, I.KEY_W, I.KEY_H), M_MOTOR, C_SLIDE, bevel=0.3)

# 磁铁：嵌在鼻子端面，底面齐平
for k, ang in enumerate(I.MAGNET_ANGLES):
    dx, dy = I.polar(I.MAGNET_R, ang)
    cyl(f"plug_magnet_{k}", (H.x + dx, H.y + dy, PLUG_END + I.MAGNET_H / 2),
        I.MAGNET_D / 2, I.MAGNET_H, M_MAG, C_SLIDE, verts=24)

# 触点针：GND 最长（先接地）、VBUS 最短
# 长度是未压缩的 pogo 行程，插入后压回；hub 场景是实心示意球，
# 针尖埋进球体属预期，不是穿模
PIN_LEN = {"GND": 1.8, "TX": 1.3, "RX": 1.3, "VBUS": 0.8}
for k, ang in enumerate(I.pad_angles(4)):
    dx, dy = I.polar(I.PAD_PITCH_R, ang)
    L = PIN_LEN[I.PIN_NAMES[k]]
    cyl(f"plug_pin_{k}", (H.x + dx, H.y + dy, PLUG_END - L / 2),
        0.75, L, M_STEEL, C_SLIDE, verts=12)

# 摩擦环：O 圈坐在井壁圆柱段内（井壁 35.0–37.08；环心 36.0，避免落到井口以上）
torus("friction_ring", (H.x, H.y, PLUG_END + 0.6), I.FRICTION_R, I.FRICTION_D / 2,
      M_MOTOR, C_SLIDE, seg=64, mseg=8)

# 磁吸脱开环：外移到肩部之外才看得见（φ34 肩会盖住旧的 14.5/1.8）
torus("breakaway", (H.x, H.y, BOT - 14), 18.2, 0.8, M_STEEL, C_SLIDE, seg=64, mseg=8)

# ---------------- 球（示意）----------------
BALL_C = Vector((H.x, H.y, BALL_TOP - I.BALL_R))
bpy.ops.mesh.primitive_uv_sphere_add(segments=48, ring_count=24,
                                     radius=I.BALL_R * MM, location=BALL_C * MM)
ball = bpy.context.object
ball.name = "ball"
ball.data.materials.append(M_SHELL)
bpy.ops.object.shade_smooth()
_link(ball, C_BALL)

# 灯带已去掉：球面保持连续，状态交给背面状态灯和脸窗
# 面窗（示意：一小块深色）
bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16,
                                     radius=(I.BALL_R + 0.5) * MM, location=BALL_C * MM)
win = bpy.context.object
win.name = "ball_win"
win.data.materials.append(M_GLASS)
win.scale = (0.42, 0.16, 0.20)
bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
win.location = Vector((BALL_C.x, BALL_C.y + 33, BALL_C.z)) * MM
bpy.ops.object.shade_smooth()
_link(win, C_BALL)

# ---------------- 四根线 ----------------
for i, A in enumerate(ANCHORS, 1):
    d = A - H
    d.z = 0
    d.normalize()
    lug = H + d * 30 + Vector((0, 0, -1))
    end = lug + (A - lug).normalized() * 26
    cu = bpy.data.curves.new(f"cable_{i}", 'CURVE')
    cu.dimensions = '3D'
    cu.bevel_depth = 1.2 * MM
    cu.bevel_resolution = 2
    sp = cu.splines.new('POLY')
    sp.points.add(1)
    sp.points[0].co = (*lug * MM, 1.0)
    sp.points[1].co = (*end * MM, 1.0)
    ob = bpy.data.objects.new(f"cable_{i}", cu)
    ob.data.materials.append(M_STEEL)
    C_STATIC.objects.link(ob)

# 供电线两股
cu = bpy.data.curves.new("tether_a", 'CURVE')
cu.dimensions = '3D'
cu.bevel_depth = 1.0 * MM
sp = cu.splines.new('POLY')
sp.points.add(1)
sp.points[0].co = (PUL.x - 10, PUL.y, PUL.z + 60, 1.0)
sp.points[1].co = (PUL.x, PUL.y + 15, PUL.z + 15, 1.0)
ob = bpy.data.objects.new("tether_a", cu)
ob.data.materials.append(M_WIRE)
C_STATIC.objects.link(ob)

# ---------------- 地面 ----------------
box("floor", (H.x, H.y, BALL_C.z - 70), (500, 500, 4), M_FLOOR, C_LIGHT)

# ============================================================
# 灯光 / 相机
# ============================================================
world = bpy.data.worlds.new("World")
bpy.context.scene.world = world
world.use_nodes = True
world.node_tree.nodes["Background"].inputs[0].default_value = (0.02, 0.024, 0.031, 1.0)
world.node_tree.nodes["Background"].inputs[1].default_value = 1.0

aim = Vector((H.x, H.y, H.z - 90))

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

area("key",  (H.x - 260, H.y + 320, H.z + 120), 12, 320, (1.0, 0.96, 0.90))
area("fill", (H.x + 360, H.y + 240, H.z - 60), 5, 300, (0.72, 0.84, 1.0))
area("rim",  (H.x + 120, H.y - 300, H.z + 60), 7, 300, (0.55, 0.88, 1.0))

cam_data = bpy.data.cameras.new("Cam")
cam_data.lens = 70
cam = bpy.data.objects.new("Cam", cam_data)
cam.location = Vector((H.x + 230, H.y + 330, H.z + 30)) * MM
C_LIGHT.objects.link(cam)
bpy.context.scene.camera = cam
tgt = bpy.data.objects.new("CamTgt", None)
tgt.location = aim * MM
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
gl.size = 6
cp = tree.nodes.new("CompositorNodeComposite")
tree.links.new(rl.outputs["Image"], gl.inputs["Image"])
tree.links.new(gl.outputs["Image"], cp.inputs["Image"])

# ============================================================
# 输出
# ============================================================
argv = sys.argv
out_dir = os.path.join(HERE, "out", "hub")
do_render = False
if "--" in argv:
    rest = argv[argv.index("--") + 1:]
    if "--out" in rest:
        out_dir = rest[rest.index("--out") + 1]
    do_render = "--render" in rest

os.makedirs(out_dir, exist_ok=True)
bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(os.path.join(out_dir, "coreball_hub.blend")))

print("=" * 52)
print("吊点总成：偏航 360° + 伸缩 0–90mm")
print("=" * 52)

if do_render:
    def shoot(path, cam_loc, tgt_loc, lens, res=1600):
        cam.location = Vector(cam_loc) * MM
        tgt.location = Vector(tgt_loc) * MM
        cam_data.lens = lens
        sc.render.resolution_x = res
        sc.render.resolution_y = res
        sc.render.filepath = os.path.abspath(os.path.join(out_dir, path))
        sc.render.image_settings.file_format = 'PNG'
        bpy.ops.render.render(write_still=True)
        print("shot:", path)

    shoot("hub_front_%d.png" % EXT_OUT, (H.x, H.y + 420, H.z - 80), (H.x, H.y, H.z - 80), 80)
    shoot("hub_3q_%d.png" % EXT_OUT,    (H.x + 260, H.y + 330, H.z + 40), (H.x, H.y, H.z - 90), 70)
    shoot("hub_side_%d.png" % EXT_OUT,  (H.x + 430, H.y, H.z - 80), (H.x, H.y, H.z - 80), 80)
    shoot("hub_top_%d.png" % EXT_OUT,   (H.x + 30, H.y + 60, H.z + 380), (H.x, H.y, H.z - 40), 80)
