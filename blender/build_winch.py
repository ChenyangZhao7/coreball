"""
CoreBall - 两套绞盘总成

A  承力绞盘 ×4（一模一样）
   竖直卷筒 + 沿墙 205mm 斜撑 + 墙平面出线滑轮 + 负荷销测张力 + 编码器

B  供电张紧器 ×1（不同）
   弹簧恒力盘 + 转向滑轮 + 固定锚点，线绕吊点小滑轮往返
   无线圈、无滑环、无电机

用法：
  blender --background --python build_winch.py -- --out blender/out/winch --render
"""

import bpy
import sys
import os
import math
from math import sin, cos, pi, radians
from mathutils import Vector

MM = 0.001

# ============================================================
# 工具
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


def line(name, p1, p2, radius, mat, coll):
    cu = bpy.data.curves.new(name, 'CURVE')
    cu.dimensions = '3D'
    cu.bevel_depth = radius * MM
    cu.bevel_resolution = 2
    sp = cu.splines.new('POLY')
    sp.points.add(1)
    sp.points[0].co = (*Vector(p1) * MM, 1.0)
    sp.points[1].co = (*Vector(p2) * MM, 1.0)
    ob = bpy.data.objects.new(name, cu)
    ob.data.materials.append(mat)
    coll.objects.link(ob)
    return ob


reset()

C_A = collection("A_承力绞盘")
C_B = collection("B_供电张紧器")
C_L = collection("灯光相机")

M_DARK  = material("Motor", (0.07, 0.075, 0.085), 0.35, 0.45)
M_ALLOY = material("Alloy", (0.72, 0.74, 0.77), 0.92, 0.24)
M_STEEL = material("Steel", (0.85, 0.86, 0.88), 0.98, 0.16)
M_FRAME = material("Frame", (0.20, 0.21, 0.23), 0.55, 0.38)
M_PCB   = material("PCB", (0.05, 0.26, 0.18), 0.2, 0.55)
M_LINE  = material("Dyneema", (0.92, 0.93, 0.94), 0.0, 0.26)
M_WIRE  = material("Wire", (0.10, 0.10, 0.12), 0.1, 0.55)
M_SPRING= material("Spring", (0.62, 0.64, 0.68), 0.95, 0.20)
M_FLOOR = material("Floor", (0.06, 0.065, 0.07), 0.0, 0.85)

# ============================================================
# A. 承力绞盘
# 竖直卷筒，线沿墙走 205mm，到墙平面出线滑轮转向下
# ============================================================
DRUM_Z   = 45.0
DRUM_R   = 17.0
DRUM_W   = 26.0
ARM_X    = 205.0       # 沿墙走线 205 mm
SHEAVE_R = 17.0
SH_Z     = 116.0       # 出线滑轮抬高 120 mm，在墙平面

# 壁板
box("A_plate", (0, 0, 0), (112, 8, 250), M_FRAME, C_A, bevel=2)


# 电机（竖直）
box("A_motor", (0, 0, 96), (42.3, 42.3, 48), M_DARK, C_A, bevel=2)
box("A_motor_mount", (0, 0, 128), (54, 54, 10), M_FRAME, C_A, bevel=2)
cyl("A_encoder", (0, 0, 135), 9, 3, M_DARK, C_A, verts=32)

# 联轴器 + 轴
cyl("A_coupling", (0, 0, 66), 9, 16, M_ALLOY, C_A, verts=24)
cyl("A_shaft", (0, 0, DRUM_Z + DRUM_W / 2 + 4), 4, 22, M_STEEL, C_A, verts=20)

# 卷筒（竖直轴）
cyl("A_drum", (0, 0, DRUM_Z), DRUM_R, DRUM_W, M_ALLOY, C_A, verts=48)
for zz in (DRUM_Z - DRUM_W / 2, DRUM_Z + DRUM_W / 2):
    cyl(f"A_flange_{int(zz)}", (0, 0, zz), DRUM_R + 5, 2, M_ALLOY, C_A, verts=48)

# 下端轴承座
box("A_bearing", (0, 0, 14), (50, 50, 20), M_FRAME, C_A, bevel=2)

# 沿墙斜撑 205 mm，把出线滑轮送到墙平面
strut_len = math.hypot(ARM_X, SH_Z - 22.0)
cyl("A_strut", (ARM_X / 2, 0, (SH_Z + 22.0) / 2), 7, strut_len,
    M_FRAME, C_A, direction=(ARM_X, 0, SH_Z - 22.0), verts=16)

# 出线滑轮（轴沿 Y，滑轮在墙平面，暴露）
for yy in (-18.0, 18.0):
    box(f"A_cheek_{int(yy)}", (ARM_X, yy, SH_Z + 4), (44, 5, 38), M_FRAME, C_A, bevel=1)
cyl("A_sheave", (ARM_X, 0, SH_Z), SHEAVE_R, 12, M_STEEL, C_A,
    direction=(0, 1, 0), verts=44)
# 负荷销（穿过滑轮的轴，测张力）
cyl("A_loadpin", (ARM_X, 0, SH_Z), 4, 54, M_ALLOY, C_A, direction=(0, 1, 0), verts=20)
for yy in (-30.0, 30.0):
    cyl(f"A_pin_cap_{int(yy)}", (ARM_X, yy, SH_Z), 9, 8, M_DARK, C_A,
        direction=(0, 1, 0), verts=24)

# 线：卷筒 -> 滑轮顶 -> 滑轮底 -> 下去
line("A_line_in", (0, DRUM_R, DRUM_Z), (ARM_X, 0, SH_Z + SHEAVE_R), 0.45, M_LINE, C_A)
line("A_line_wrap", (ARM_X, 0, SH_Z + SHEAVE_R), (ARM_X, 0, SH_Z - SHEAVE_R), 0.45, M_LINE, C_A)
line("A_line_out", (ARM_X, 0, SH_Z - SHEAVE_R), (ARM_X, 0, SH_Z - 380), 0.45, M_LINE, C_A)

# 电源与信号线（拖到壁板后面）
for k, xx in enumerate((-34.0, -24.0, -14.0)):
    line(f"A_wire_{k}", (xx, 0, 96), (xx, -6, -100), 0.8, M_WIRE, C_A)

# ============================================================
# B. 供电张紧器
# ============================================================
B = Vector((760, 0, 0))
HUB_DROP = -560.0

def bb(name, off, size, mat, bevel=0.0):
    return box(name, (B.x + off[0], B.y + off[1], B.z + off[2]), size, mat, C_B, bevel)

def bc(name, off, r, d, mat, direction=(0, 0, 1), verts=32):
    return cyl(name, (B.x + off[0], B.y + off[1], B.z + off[2]), r, d, mat, C_B,
               direction=direction, verts=verts)

# 顶棚安装板
bb("B_plate", (0, 0, 0), (200, 118, 8), M_FRAME, bevel=2)

# 弹簧恒力盘
bc("B_reel_house", (-62, 0, -24), 32, 20, M_DARK, direction=(0, 1, 0), verts=48)
bc("B_reel_drum", (-62, 0, -24), 25, 12, M_ALLOY, direction=(0, 1, 0), verts=48)
torus("B_reel_spring", (B.x - 62, B.y, B.z - 24), 16, 2.4, M_SPRING, C_B,
      direction=(0, 1, 0), seg=48, mseg=8)

# 转向滑轮
for xx in (-3.0, 27.0):
    bb(f"B_cheek_{int(xx)}", (xx, 0, -34), (6, 40, 46), M_FRAME, bevel=1)
bc("B_sheave", (12, 0, -38), 16, 10, M_STEEL, direction=(1, 0, 0), verts=44)
bc("B_axle", (12, 0, -38), 3.5, 46, M_ALLOY, direction=(1, 0, 0), verts=16)

# 固定锚点（线端死在这里）
bb("B_anchor", (86, 0, -20), (26, 26, 22), M_ALLOY, bevel=2)
torus("B_eye", (B.x + 86, B.y, B.z - 38), 6, 2.4, M_STEEL, C_B,
      direction=(0, 1, 0), seg=24, mseg=8)

# 吊点上的小滑轮（示意）
bb("B_hub_yoke", (0, 0, HUB_DROP + 34), (22, 44, 26), M_FRAME, bevel=2)
bc("B_hub_sheave", (0, 0, HUB_DROP), 16, 10, M_STEEL, direction=(1, 0, 0), verts=44)
bc("B_hub_axle", (0, 0, HUB_DROP), 3.5, 38, M_ALLOY, direction=(1, 0, 0), verts=16)

# 两根线：盘 -> 吊点滑轮 -> 锚点
line("B_wire_1", (B.x - 62, B.y, B.z - 40), (B.x, B.y, B.z + HUB_DROP + 16), 0.55, M_WIRE, C_B)
line("B_wire_2", (B.x, B.y, B.z + HUB_DROP + 16), (B.x + 86, B.y, B.z - 44), 0.55, M_WIRE, C_B)

# ============================================================
# 地面 / 灯光 / 相机
# ============================================================
box("floor", (0, 0, -780), (3200, 3200, 20), M_FLOOR, C_A)

world = bpy.data.worlds.new("World")
bpy.context.scene.world = world
world.use_nodes = True
world.node_tree.nodes["Background"].inputs[0].default_value = (0.018, 0.022, 0.028, 1.0)
world.node_tree.nodes["Background"].inputs[1].default_value = 1.0

aim = Vector((360, 0, -60))

def area(name, loc, energy, size, color):
    d = bpy.data.lights.new(name, 'AREA')
    d.energy = energy
    d.size = size * MM
    d.color = color
    ob = bpy.data.objects.new(name, d)
    ob.location = Vector(loc) * MM
    C_L.objects.link(ob)
    e = bpy.data.objects.new(f"aim_{name}", None)
    e.location = aim * MM
    C_L.objects.link(e)
    c = ob.constraints.new('TRACK_TO')
    c.target = e
    c.track_axis = 'TRACK_NEGATIVE_Z'
    c.up_axis = 'UP_Y'
    return ob

area("key",  (-420, 600, 480), 26, 400, (1.0, 0.96, 0.90))
area("fill", (1000, 420, 200), 9, 350, (0.72, 0.84, 1.0))
area("rim",  (300, -620, 400), 12, 350, (0.55, 0.88, 1.0))

cam_data = bpy.data.cameras.new("Cam")
cam_data.lens = 62
cam = bpy.data.objects.new("Cam", cam_data)
cam.location = Vector((560, 780, 300)) * MM
C_L.objects.link(cam)
bpy.context.scene.camera = cam
tgt = bpy.data.objects.new("CamTgt", None)
tgt.location = aim * MM
C_L.objects.link(tgt)
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
gl.threshold = 1.0
gl.size = 6
cp = tree.nodes.new("CompositorNodeComposite")
tree.links.new(rl.outputs["Image"], gl.inputs["Image"])
tree.links.new(gl.outputs["Image"], cp.inputs["Image"])

# ============================================================
# 输出
# ============================================================
argv = sys.argv
HERE = os.path.dirname(os.path.abspath(__file__)) if "__file__" in dir() else os.getcwd()
out_dir = os.path.join(HERE, "out", "winch")
do_render = False
if "--" in argv:
    rest = argv[argv.index("--") + 1:]
    if "--out" in rest:
        out_dir = rest[rest.index("--out") + 1]
    do_render = "--render" in rest

os.makedirs(out_dir, exist_ok=True)
bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(os.path.join(out_dir, "coreball_winch.blend")))

print("=" * 52)
print("A 承力绞盘：卷筒 φ34 竖直，沿墙 205mm 斜撑，滑轮在墙平面")
print("B 供电张紧器：弹簧恒力盘，无线圈 / 无滑环 / 无电机")
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

    shoot("winch_front.png", (0, 900, 40), (0, 60, -20), 70)
    shoot("winch_3q.png",    (700, 780, 330), (0, 70, -30), 62)
    shoot("winch_side.png",  (860, 120, 40), (0, 60, -30), 70)

    shoot("tension_front.png", (B.x, 950, -260), (B.x, 0, -280), 50)
    shoot("tension_3q.png",    (B.x + 620, 720, 40), (B.x, 0, -290), 45)
    shoot("tension_side.png",  (B.x + 950, 20, -260), (B.x, 0, -280), 50)
