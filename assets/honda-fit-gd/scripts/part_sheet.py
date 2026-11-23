"""Render each part of the aligned candidate ALONE (grey, studio light) from the front 3/4, to tell exterior from interior."""
import math, os, sys
import bpy
from mathutils import Vector
out = sys.argv[sys.argv.index('--') + 1]
os.makedirs(out, exist_ok=True)
scn = bpy.context.scene
scn.render.engine = 'BLENDER_WORKBENCH'; scn.view_settings.view_transform = 'Standard'
sh = scn.display.shading; sh.light = 'STUDIO'; sh.color_type = 'SINGLE'; sh.single_color = (0.75, 0.75, 0.78); sh.show_object_outline = True
w = bpy.data.worlds.new('w'); w.color = (0.12, 0.12, 0.14); scn.world = w
cd = bpy.data.cameras.new('c'); cam = bpy.data.objects.new('c', cd); scn.collection.objects.link(cam); scn.camera = cam
cd.lens = 50
scn.render.resolution_x, scn.render.resolution_y = 520, 360
# front is +Y in this file: look from the front-left (x>0, y>0)
cam.location = (5.2, 5.6, 2.6)
cam.rotation_euler = (Vector((0, 0, 0.7)) - cam.location).to_track_quat('-Z', 'Y').to_euler()
meshes = [o for o in bpy.data.objects if o.type == 'MESH']
for o in meshes:
    if o.name.startswith(('2_00', 'Object00', '1_00')):
        continue   # tyres, rims and tiny discs: not in doubt
    for m in meshes:
        m.hide_render = (m is not o)
    scn.render.filepath = os.path.join(out, 'part_' + o.name.split(' ')[0].replace('#', '') + '.png')
    bpy.ops.render.render(write_still=True)
print('DONE')
