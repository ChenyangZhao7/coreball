"""从 coreball_rig.blend 生成「三维指挥」场景。

用法：
  blender -b --python blender/build_command.py -- --out blender/out/cmd

做的事：
  1. 打开现成工位场景（不重建任何模型）
  2. 加 CMD_TARGET（球心）和 HUB_ROOT（球心 +160）
  3. 球和整个吊点挂到控制点上，拖动即跟随
  4. 八根承力候选线和两根供电线用 Hook 挂到真实端点
  5. 另存为 coreball_command.blend
"""
import bpy
import os
import sys
import math
from mathutils import Vector, Matrix

HERE = os.path.dirname(os.path.abspath(__file__))
RIG = os.path.join(HERE, "out", "rig", "coreball_rig.blend")
HUB_GAP = 0.160          # 米；球心到吊点中心
C_CMD = "07_指挥"
C_PERSON = "08_人"


def parse_out():
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    else:
        argv = []
    out = os.path.join(HERE, "out", "cmd")
    for i, a in enumerate(argv):
        if a == "--out" and i + 1 < len(argv):
            out = argv[i + 1]
    return os.path.abspath(out)


def reparent(ob, parent):
    """改父级但保持世界位置不变。"""
    bpy.context.view_layer.update()
    mw = ob.matrix_world.copy()
    ob.parent = parent
    ob.matrix_parent_inverse = Matrix.Identity(4)
    ob.matrix_basis = parent.matrix_world.inverted() @ mw
    bpy.context.view_layer.update()


def need(name):
    ob = bpy.data.objects.get(name)
    if ob is None:
        raise RuntimeError("场景里缺少对象 %r，拒绝生成半成品" % name)
    return ob


def hook(ob, index, target_obj):
    """把曲线的一个控制点挂到某个对象的当前世界上。"""
    m = ob.modifiers.new("hook_" + target_obj.name, 'HOOK')
    m.object = target_obj
    m.matrix_inverse = target_obj.matrix_world.inverted()
    m.vertex_indices_set([index])


def mesh_into(ob, coll):
    for c in list(ob.users_collection):
        c.objects.unlink(ob)
    coll.objects.link(ob)
    return ob


def material(name, color, rough=0.7):
    m = bpy.data.materials.get(name)
    if m is None:
        m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes.get("Principled BSDF")
    if b is not None:
        b.inputs["Base Color"].default_value = (*color, 1.0)
        b.inputs["Roughness"].default_value = rough
    return m


def sphere(name, loc, r, mat):
    bpy.ops.mesh.primitive_uv_sphere_add(radius=r, segments=32, ring_count=16, location=loc)
    ob = bpy.context.object
    ob.name = name
    ob.data.materials.append(mat)
    return ob


def cylinder(name, loc, r, depth, mat):
    bpy.ops.mesh.primitive_cylinder_add(radius=r, depth=depth, vertices=32, location=loc)
    ob = bpy.context.object
    ob.name = name
    ob.data.materials.append(mat)
    return ob


def cone(name, loc, r, depth, mat):
    bpy.ops.mesh.primitive_cone_add(radius1=r, depth=depth, vertices=24, location=loc)
    ob = bpy.context.object
    ob.name = name
    ob.data.materials.append(mat)
    return ob


def box(name, loc, size, mat, rot=(0, 0, 0)):
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=loc, rotation=rot)
    ob = bpy.context.object
    ob.name = name
    ob.scale = size
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    ob.data.materials.append(mat)
    return ob


def torus(name, loc, major, minor, mat):
    bpy.ops.mesh.primitive_torus_add(location=loc, major_radius=major,
                                     minor_radius=minor, major_segments=32,
                                     minor_segments=8)
    ob = bpy.context.object
    ob.name = name
    ob.data.materials.append(mat)
    return ob


def join_meshes(coll, new_name):
    """把一个集合里的网格合并成一个：179 个对象 → 1 个，弱机器上差别很大。"""
    objs = [o for o in coll.objects if o.type == 'MESH']
    if len(objs) < 2:
        return None
    bpy.ops.object.select_all(action='DESELECT')
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.object.join()
    objs[0].name = new_name
    return objs[0]


def empty(name, loc, size, kind='SPHERE'):
    ob = bpy.data.objects.new(name, None)
    ob.empty_display_type = kind
    ob.empty_display_size = size
    ob.show_name = True
    coll.objects.link(ob)
    ob.location = loc
    return ob


def main():
    out_dir = parse_out()
    print("打开:", RIG)
    bpy.ops.wm.open_mainfile(filepath=RIG)

    global coll
    coll = bpy.data.collections.get(C_CMD)
    if coll is None:
        coll = bpy.data.collections.new(C_CMD)
        bpy.context.scene.collection.children.link(coll)

    ball_root = need("ball_root")
    ball_pos = ball_root.matrix_world.translation.copy()

    target = empty("CMD_TARGET", ball_pos, 0.06)
    hub_root = empty("HUB_ROOT", ball_pos + Vector((0, 0, HUB_GAP)), 0.05, 'PLAIN_AXES')

    reparent(ball_root, target)
    reparent(hub_root, target)

    hub_coll = bpy.data.collections.get("04_吊点")
    if hub_coll is None:
        raise RuntimeError("找不到集合 04_吊点")
    for ob in list(hub_coll.objects):
        reparent(ob, hub_root)

    for i in range(1, 9):
        hook(need("cable_%d" % i), 1, need("lug_%d" % i))

    sheave = need("tether_sheave")
    hook(need("wire_1"), 1, sheave)
    hook(need("wire_2"), 0, sheave)

    # ---------------- 演示减负 ----------------
    gray = material("PERSON", (0.45, 0.47, 0.50), 0.8)
    join_meshes(bpy.data.collections["05_球"], "ball_mesh")
    winches = bpy.data.collections.get("02_绞盘")
    if winches is not None:
        winches.hide_viewport = True
    for i in range(1, 9):
        cu = bpy.data.objects["cable_%d" % i].data
        p = cu.splines[0].points[0].co
        mesh_into(sphere("anchor_%d" % i, (p.x, p.y, p.z), 0.010, gray), coll)
    bpy.context.view_layer.update()

    # ---------------- 人 ----------------
    # 人物模型已在 coreball_rig.blend 里（08_人）；这里只保留朝向用的空物体
    person_coll = bpy.data.collections.get(C_PERSON)
    if person_coll is None:
        person_coll = bpy.data.collections.new(C_PERSON)
        bpy.context.scene.collection.children.link(person_coll)

    head = Vector((0, 0.890, 1.250))
    person_head = empty("PERSON_HEAD", head, 0.05, 'PLAIN_AXES')

    # ---------------- 命名点（用户可以在 Blender 里拖）----------------
    empty("TGT_HOME", Vector((-0.430, 0.760, 1.420)), 0.05, 'CUBE')
    empty("TGT_NEAR", Vector((-0.380, 0.520, 1.300)), 0.05, 'CUBE')

    # ---------------- 小机器人（球完全在里面）----------------
    rover_coll = bpy.data.collections.get("09_小车")
    if rover_coll is None:
        rover_coll = bpy.data.collections.new("09_小车")
        bpy.context.scene.collection.children.link(rover_coll)

    home = Vector((0.600, 0.250, 0.0))
    rover_root = empty("ROVER_ROOT", home, 0.05, 'CUBE')
    mesh_into(rover_root, rover_coll)

    rdark = material("ROVER", (0.16, 0.17, 0.19), 0.55)
    rubber = material("Rubber", (0.04, 0.04, 0.05), 0.9)
    led = material("ROVER_LED", (0.12, 0.72, 1.0), 0.25)
    node = led.node_tree.nodes.get("Principled BSDF")
    if node is not None:
        node.inputs["Emission Color"].default_value = (0.40, 0.85, 1.0, 1.0)
        node.inputs["Emission Strength"].default_value = 0.05

    parts = [box("rover_body", home + Vector((0, 0, 0.085)),
                 (0.20, 0.16, 0.09), rdark)]
    for sx, nm in ((-1, "rover_wheel_l"), (1, "rover_wheel_r")):
        bpy.ops.mesh.primitive_cylinder_add(
            radius=0.030, depth=0.024, vertices=32,
            location=home + Vector((sx * 0.095, 0, 0.030)),
            rotation=(0, math.radians(90), 0))
        w = bpy.context.object
        w.name = nm
        w.data.materials.append(rubber)
        parts.append(w)
    parts.append(sphere("rover_caster", home + Vector((0, -0.070, 0.015)), 0.015, rubber))
    parts.append(torus("rover_light", home + Vector((0, 0, 0.133)), 0.045, 0.008, led))

    for p in parts:
        mesh_into(p, rover_coll)
        reparent(p, rover_root)
    join_meshes(rover_coll, "rover_mesh")

    empty("TGT_ROVER_HOME", Vector((0.600, 0.250, 0.0)), 0.05, 'CUBE')
    empty("TGT_ROVER_NEAR", Vector((-0.450, 0.650, 0.0)), 0.05, 'CUBE')

    for ob in bpy.context.view_layer.objects:
        ob.select_set(False)
    target.select_set(True)
    bpy.context.view_layer.objects.active = target

    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "coreball_command.blend")
    tmp = path + ".tmp.blend"
    bpy.ops.wm.save_as_mainfile(filepath=tmp)
    os.replace(tmp, path)
    print("已保存:", path)


if __name__ == "__main__":
    main()
