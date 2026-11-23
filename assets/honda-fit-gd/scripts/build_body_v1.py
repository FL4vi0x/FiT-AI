"""
Honda Fit LX 2005 BR (GD) - STAGE 2: exterior body only (grey, no details). Run inside Blender:
    blender --background --python scripts/build_body.py

Method: the body is LOFTED from measured profiles (data/profiles.json: side roofline, plan half-width, front-view width by height,
all in metres, calibrated on the Honda manual: 3830 x 1675 x 1525 mm, wheelbase 2450 mm). One half (x >= 0) is built and a Mirror
modifier makes the other, so the model stays editable. Not a box and not extruded cylinders: every station is a cross-section whose
height, width and wheel-arch cut come from the measurements.

Axes (Blender): +Z up, the car's FRONT is -Y, its LEFT side is +X, origin on the ground at the centre of the wheelbase.
glTF export converts to +Y up and the front ends up facing +Z (the usual glTF convention).
"""
import json
import math
import os
import sys

import bmesh
import bpy
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = json.load(open(os.path.join(ROOT, 'data', 'profiles.json')))
OUT = os.path.join(ROOT, 'out', 'v1')
os.makedirs(OUT, exist_ok=True)

L, W, H, WB = 3.830, 1.675, 1.525, 2.450
TRACK_F, TRACK_R = 1.460, 1.445
S_PX = DATA['meta']['px_per_m']
VF = DATA['meta']['vertical_factor']
R_WHEEL = DATA['wheel_radius_m']          # 0.29 m (blueprint) - 175/65R14 is ~0.29-0.30 m
Y_MID = (DATA['axle_px'][0] + DATA['axle_px'][1]) / 2          # px
T_MID = (Y_MID - 5) / S_PX                                    # distance nose -> middle of the wheelbase
T_FRONT_AXLE = T_MID - WB / 2
T_REAR_AXLE = T_MID + WB / 2


def interp(table, t):
    """linear interpolation of [[t, v], ...]"""
    if t <= table[0][0]:
        return table[0][1]
    for (a, va), (b, vb) in zip(table, table[1:]):
        if a <= t <= b:
            return va + (vb - va) * ((t - a) / (b - a) if b > a else 0)
    return table[-1][1]


def smooth(table, win=2, keep_ends=2):
    out = []
    n = len(table)
    for i, (t, v) in enumerate(table):
        if i < keep_ends or i >= n - keep_ends:
            out.append([t, v])
            continue
        lo, hi = max(0, i - win), min(n, i + win + 1)
        out.append([t, sum(p[1] for p in table[lo:hi]) / (hi - lo)])
    return out


TOP = smooth(DATA['top_profile'], win=3)
HALFW = smooth(DATA['plan_halfwidth'], win=2)
# the measured roof tops out at 1.5209 m; the manual says 1.525 m
TOP_MAX = max(v for _, v in TOP)
CROWN = 0.024
TOP = [[t, v * ((H - CROWN) / TOP_MAX)] for t, v in TOP]
HW_MAX = max(v for _, v in HALFW)
HALFW = [[t, v * (W / 2 / HW_MAX)] for t, v in HALFW]

# body bottom (underbody / bumper lip) from the side view, by distance from the nose (m)
BOTTOM = [[0.0, 0.343], [0.042, 0.266], [0.106, 0.225], [0.212, 0.204], [0.5, 0.2], [3.2, 0.2], [3.49, 0.186], [3.66, 0.192], [3.766, 0.241], [3.83, 0.331]]

# front-view half width as a fraction of the body half width, by height above the ground (the door mirrors row was removed)
FRONT_W = [[0.0, 0.955], [0.20, 0.972], [0.42, 0.985], [0.62, 1.0], [0.80, 1.0], [0.92, 0.985], [1.03, 0.90], [1.157, 0.85], [1.28, 0.80], [1.40, 0.72], [1.47, 0.60], [1.50, 0.40], [H, 0.14]]

BELT = 0.96          # belt line (top of the doors) in metres
K1, K2 = 9, 8       # side-wall levels below / above the belt line (the belt is always an exact level)
K = K1 + K2


def wn(h):
    return interp(FRONT_W, h)


def sstep(a, b, v):
    x = min(1.0, max(0.0, (v - a) / (b - a)))
    return x * x * (3 - 2 * x)


def end_taper(t, h):
    """the plan half-width is the WIDEST height (the bumpers); the upper body is narrower at the nose and the tail"""
    tail = sstep(3.45, 3.83, t) * min(1.0, max(0.0, (h - 0.55) / 0.45)) * 0.30
    nose = sstep(0.38, 0.0, t) * min(1.0, max(0.0, (h - 0.55) / 0.35)) * 0.20
    return tail + nose


def arch_height(t):
    """height of the wheel-arch roof at station t (0 outside the arches)"""
    best = 0.0
    for ta in (T_FRONT_AXLE, T_REAR_AXLE):
        r = 0.335
        d = abs(t - ta)
        if d < r:
            best = max(best, R_WHEEL + math.sqrt(r * r - d * d))
    return best


def half_section(t):
    """points (x, z) of the half cross-section at station t, from the bottom centre up to the top centre"""
    hb = interp(BOTTOM, t)
    ht = interp(TOP, t)
    hw = max(0.012, interp(HALFW, t))
    # the plan outline closes to a point at the very tip (no flat cap): a square-root taper over the first/last 15 mm
    hw *= max(math.sqrt(min(1.0, min(t, L - t) / 0.015)), 0.04)
    # a rounded nose and tail: the plan width closes to a rounded tip, and the section height closes too
    hs = max(hb + 0.035, min(arch_height(t), ht - 0.12))
    pts = [(0.0, hb), (hw * 0.70, hb)]
    ub = max(min((BELT - hs) / max(ht - hs, 1e-6), 0.93), 0.35)
    for k in range(K + 1):
        u = ub * (k / K1) ** 0.92 if k <= K1 else ub + (1 - ub) * ((k - K1) / K2)
        h = hs + (ht - hs) * u
        x = hw * wn(h) * (1 - end_taper(t, h))
        if k == K:
            h, x = ht - 0.014, x * 0.9
        elif k == K - 1:
            x *= 0.985
        pts.append((x, h))
    xk, hk = pts[-1]
    pts += [(xk * 0.62, ht + 0.006), (xk * 0.30, ht + 0.018), (0.0, ht + 0.024)]
    return pts


# stations: cosine spacing clusters them at nose and tail
N = 128
ts = [L * (1 - math.cos(math.pi * i / (N - 1))) / 2 for i in range(N)]
ts[0], ts[-1] = 0.0, L


def y_of(t):
    return t - T_MID           # front (t = 0) is -Y


def build():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scn = bpy.context.scene
    scn.unit_settings.system = 'METRIC'
    scn.unit_settings.scale_length = 1.0

    mesh = bpy.data.meshes.new('BodyMesh')
    bm = bmesh.new()
    rings = []
    for t in ts:
        ring = [bm.verts.new((x, y_of(t), z)) for x, z in half_section(t)]
        rings.append(ring)
    m = len(rings[0])
    quad_faces = {}
    for i, (a, b) in enumerate(zip(rings, rings[1:])):
        for j in range(m - 1):
            try:
                quad_faces[(i, j)] = bm.faces.new((a[j], a[j + 1], b[j + 1], b[j]))
            except ValueError:
                quad_faces[(i, j)] = None
    # nose and tail caps
    for ring, flip in ((rings[0], False), (rings[-1], True)):
        # a fan around the centre of the profile (the half profile is concave, one big polygon would tessellate badly)
        cx = sum(v.co.x for v in ring) / len(ring)
        cy = ring[0].co.y
        cz = sum(v.co.z for v in ring) / len(ring)
        centre = bm.verts.new((0.0, cy, cz))
        for a, b in zip(ring, ring[1:]):
            try:
                bm.faces.new((centre, b, a) if flip else (centre, a, b))
            except ValueError:
                pass
        try:
            bm.faces.new((centre, ring[0], ring[-1]) if False else (centre, ring[-1], ring[0]) if flip else (centre, ring[0], ring[-1]))
        except ValueError:
            pass
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.normal_update()

    # materials: body grey, glazing darker grey. Glass = above the belt line on the greenhouse sides, windscreen and tail window
    body_mat = bpy.data.materials.new('Grey_Body')
    body_mat.diffuse_color = (0.66, 0.66, 0.68, 1)
    glass_mat = bpy.data.materials.new('Grey_Glass')
    glass_mat.diffuse_color = (0.20, 0.21, 0.23, 1)
    mesh.materials.append(body_mat)
    mesh.materials.append(glass_mat)
    for f in bm.faces:
        f.smooth = True
        f.material_index = 0
    # glazing = the profile rows above the belt level on the greenhouse stations, plus windscreen and tail window
    for i in range(N - 1):
        t = (ts[i] + ts[i + 1]) / 2
        in_glass_zone = interp(TOP, t) > BELT + 0.09 and 0.62 <= t <= 3.62
        for j in range(m - 1):
            f = quad_faces[(i, j)]
            if f is None:
                continue
            above = (2 + K1) <= j <= (2 + K - 1)
            wind = (2 + K) <= j <= (2 + K + 1) and ((0.78 <= t <= 1.66) or (3.50 <= t <= 3.78))
            f.material_index = 1 if (in_glass_zone and (above or wind)) else 0
    bm.to_mesh(mesh)
    bm.free()
    for e in mesh.edges:
        e.use_edge_sharp = False

    body = bpy.data.objects.new('Body', mesh)
    bpy.context.collection.objects.link(body)
    mir = body.modifiers.new('Mirror', 'MIRROR')
    mir.use_axis[0] = True
    mir.use_clip = True
    mir.use_mirror_merge = True
    mir.merge_threshold = 0.0005
    return body


def add_wheels():
    tire_mat = bpy.data.materials.new('Grey_Tyre')
    tire_mat.diffuse_color = (0.07, 0.07, 0.075, 1)
    hub_mat = bpy.data.materials.new('Grey_Wheel')
    hub_mat.diffuse_color = (0.55, 0.55, 0.57, 1)
    names = {('F', 1): 'FrontLeftWheel', ('F', -1): 'FrontRightWheel', ('R', 1): 'RearLeftWheel', ('R', -1): 'RearRightWheel'}
    objs = []
    for (axle, side), name in names.items():
        track = TRACK_F if axle == 'F' else TRACK_R
        y = -WB / 2 if axle == 'F' else WB / 2
        width = 0.175
        x = side * (track / 2 + width / 2 - 0.02)
        bpy.ops.mesh.primitive_cylinder_add(vertices=48, radius=R_WHEEL, depth=width, location=(x, y, R_WHEEL), rotation=(0, math.pi / 2, 0))
        tire = bpy.context.active_object
        tire.name = name
        tire.data.materials.append(tire_mat)
        bpy.ops.object.shade_smooth()
        # simple 14" rim face (placeholder disc; detailed wheels belong to stage 3)
        bpy.ops.mesh.primitive_cylinder_add(vertices=48, radius=R_WHEEL * 0.62, depth=width + 0.004, location=(x, y, R_WHEEL), rotation=(0, math.pi / 2, 0))
        rim = bpy.context.active_object
        rim.name = name + '_Rim'
        rim.data.materials.append(hub_mat)
        rim.parent = tire
        rim.matrix_parent_inverse = tire.matrix_world.inverted()
        objs.append(tire)
    return objs


def bbox_report(body, wheels):
    deps = bpy.context.evaluated_depsgraph_get()
    ev = body.evaluated_get(deps)
    pts = [ev.matrix_world @ Vector(c) for c in ev.bound_box]
    xs, ys, zs = [p.x for p in pts], [p.y for p in pts], [p.z for p in pts]
    rep = {
        'body_bbox_m': {'width_x': round(max(xs) - min(xs), 4), 'length_y': round(max(ys) - min(ys), 4), 'height_z': round(max(zs), 4)},
        'official_m': {'width': W, 'length': L, 'height': H, 'wheelbase': WB},
        'wheelbase_m': round(abs(wheels[0].location.y - wheels[2].location.y), 4),
        'wheel_radius_m': R_WHEEL,
        'wheels': [w.name for w in wheels],
        'tris_body_evaluated': sum(len(p.vertices) - 2 for p in ev.data.polygons),
    }
    rep['deviation_mm'] = {
        'length': round((rep['body_bbox_m']['length_y'] - L) * 1000, 1),
        'width': round((rep['body_bbox_m']['width_x'] - W) * 1000, 1),
        'height': round((rep['body_bbox_m']['height_z'] - H) * 1000, 1),
    }
    return rep


def main():
    body = build()
    wheels = add_wheels()
    rep = bbox_report(body, wheels)
    json.dump(rep, open(os.path.join(OUT, 'measurements.json'), 'w'), indent=1)
    print('MEASUREMENTS', json.dumps(rep))
    blend = os.path.join(OUT, 'fit_gd_2005_lx_stage2_body.blend')
    bpy.ops.wm.save_as_mainfile(filepath=blend)
    # inspection GLB, explicitly an INCOMPLETE PREVIEW (body + 4 wheel placeholders, grey, no details)
    bpy.ops.export_scene.gltf(filepath=os.path.join(OUT, 'PREVIEW_INCOMPLETO_fit_gd_stage2.glb'), export_format='GLB', export_apply=True, export_yup=True)
    print('SAVED', blend)


main()
