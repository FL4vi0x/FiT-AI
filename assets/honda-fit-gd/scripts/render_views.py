"""
Neutral grey renders of the stage-2 body (Gate 1). Opaque grey material, studio light, NO wireframe, NO glow.
    blender --background out/fit_gd_2005_lx_stage2_body.blend --python scripts/render_views.py
Orthographic views use the SAME px-per-metre as the auxiliary blueprint, so a silhouette can be laid over it.
"""
import json
import math
import os

import bpy
from mathutils import Matrix, Vector

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'out', os.environ.get('FITGD_VERSION', 'v3'), 'renders')
os.makedirs(OUT, exist_ok=True)
D = json.load(open(os.path.join(ROOT, 'data', 'profiles.json')))
S = D['meta']['px_per_m']
VF = D['meta']['vertical_factor']
WB = 2.45
T_MID = ((D['axle_px'][0] + D['axle_px'][1]) / 2 - 5) / S

scn = bpy.context.scene
scn.render.engine = 'BLENDER_WORKBENCH'
scn.view_settings.view_transform = 'Standard'
sh = scn.display.shading
sh.light = 'STUDIO'
sh.color_type = 'MATERIAL'
sh.show_cavity = False
sh.show_shadows = False
sh.show_object_outline = True
sh.object_outline_color = (0.05, 0.05, 0.06)
scn.render.image_settings.file_format = 'PNG'
scn.render.image_settings.color_mode = 'RGBA'
world = bpy.data.worlds.new('NeutralWorld')
world.color = (0.80, 0.81, 0.83)
scn.world = world

# ground (only used by the perspective views, so the car does not float)
bpy.ops.mesh.primitive_plane_add(size=40, location=(0, 0, -0.002))
ground = bpy.context.active_object
ground.name = 'Ground'
gm = bpy.data.materials.new('Ground')
gm.diffuse_color = (0.62, 0.63, 0.65, 1)
ground.data.materials.append(gm)

cam_data = bpy.data.cameras.new('Cam')
cam = bpy.data.objects.new('Cam', cam_data)
scn.collection.objects.link(cam)
scn.camera = cam


def place(pos, right, up):
    right, up = Vector(right).normalized(), Vector(up).normalized()
    back = right.cross(up)           # camera looks along -local Z, so local Z = right x up
    m = Matrix(((right.x, up.x, back.x, pos[0]), (right.y, up.y, back.y, pos[1]), (right.z, up.z, back.z, pos[2]), (0, 0, 0, 1)))
    cam.matrix_world = m


def look(pos, target):
    d = Vector(target) - Vector(pos)
    cam.location = pos
    cam.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()


def shoot(name, res, transparent=False, ground_on=False):
    scn.render.resolution_x, scn.render.resolution_y = res
    scn.render.resolution_percentage = 100
    scn.render.film_transparent = transparent
    ground.hide_render = not ground_on
    sh.light = 'FLAT' if transparent else 'STUDIO'
    scn.render.filepath = os.path.join(OUT, name + '.png')
    bpy.ops.render.render(write_still=True)
    print('RENDERED', name)


# ---------- orthographic, calibrated on the blueprint crops ----------
def ortho(ortho_scale, res_px, pos, right, up):
    cam_data.type = 'ORTHO'
    cam_data.ortho_scale = ortho_scale
    cam_data.clip_start, cam_data.clip_end = 0.1, 100
    place(pos, right, up)


# side (blueprint crop x 5..910, rows 0..380); vertical axis compressed by VF, so render 905 x round(380*VF) and stretch back
yc = ((5 + 910) / 2 - 5) / S - T_MID
side_res = (905, round(380 * VF))
for tag, transparent in (('side', False), ('mask_side', True)):
    ortho(905 / S, side_res, (12, yc, (377 - 190) / S * VF), (0, 1, 0), (0, 0, 1))
    shoot(tag, side_res, transparent)

# front (crop x 929..1386, rows 0..380), car centre at px 1157
front_res = (457, round(380 * VF))
for tag, transparent in (('front_ortho', False), ('mask_front', True)):
    ortho(457 / S, front_res, ((1157.5 - 1157) / S, -12, (1.525 - (190 - 10) / S * VF)), (1, 0, 0), (0, 0, 1))
    shoot(tag, front_res, transparent)

# rear (no blueprint overlay: its row calibration is unknown)
ortho(2.4, (900, 600), (0, 12, 0.78), (-1, 0, 0), (0, 0, 1))
shoot('rear_ortho', (900, 600))

# top (crop x 5..912, rows 395..835): image right = +Y, image up = -X
top_res = (907, 440)
for tag, transparent in (('top', False), ('mask_top', True)):
    ortho(907 / S, top_res, ((615 - 604.5) / S, ((5 + 912) / 2 - 5) / S - T_MID, 12), (0, 1, 0), (-1, 0, 0))
    shoot(tag, top_res, transparent)

# ---------- perspective 3/4 views ----------
cam_data.type = 'PERSP'
cam_data.lens = 50
cam_data.sensor_width = 36
cam_data.clip_start, cam_data.clip_end = 0.1, 200
# straight front and rear, perspective with a long lens like the photos (85 mm, car-height camera)
cam_data.lens = 85
for name, y in (('front', -9.0), ('rear', 9.0)):
    look((0, y, 0.95), (0, 0, 0.78))
    shoot(name, (800, 600), ground_on=True)
cam_data.lens = 50
for name, az, side in (('front34', 38, -1), ('rear34', 35, 1)):
    r = 7.2
    pos = (r * math.sin(math.radians(az)), side * r * math.cos(math.radians(az)), 1.45)
    look(pos, (0, 0, 0.72))
    shoot(name, (1200, 800), ground_on=True)
