import sys, os, math, hashlib, json
import bpy
from mathutils import Vector
path, out = sys.argv[sys.argv.index('--') + 1], sys.argv[sys.argv.index('--') + 2]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=path)
ms = [o for o in bpy.data.objects if o.type == 'MESH']
h = hashlib.md5()
for o in sorted(ms, key=lambda o: o.name):
    for v in o.data.vertices:
        p = o.matrix_world @ v.co
        h.update(('%.5f,%.5f,%.5f;' % (p.x, p.y, p.z)).encode())
pts = [o.matrix_world @ Vector(c) for o in ms for c in o.bound_box]
mn = [min(getattr(p, a) for p in pts) for a in 'xyz']; mx = [max(getattr(p, a) for p in pts) for a in 'xyz']
print('GEOM_HASH', h.hexdigest(), 'bbox', [round(mx[i]-mn[i], 4) for i in range(3)], 'min', [round(v,4) for v in mn], 'max', [round(v,4) for v in mx])
# scale to ~4 units along its longest axis and render 4 orthographic probes
L = max(mx[i] - mn[i] for i in range(3)); s = 4.0 / L
c = Vector(((mn[0]+mx[0])/2, (mn[1]+mx[1])/2, (mn[2]+mx[2])/2))
for o in ms:
    pass
root = bpy.data.objects.new('r', None); bpy.context.collection.objects.link(root)
for o in bpy.data.objects:
    if o.type == 'MESH':
        o.parent = root
root.scale = (s, s, s); root.location = -c * s
scn = bpy.context.scene; scn.render.engine = 'BLENDER_WORKBENCH'; scn.view_settings.view_transform = 'Standard'
scn.display.shading.light = 'STUDIO'; scn.display.shading.color_type = 'MATERIAL'
w = bpy.data.worlds.new('w'); w.color = (0.85, 0.85, 0.87); scn.world = w
cd = bpy.data.cameras.new('c'); cam = bpy.data.objects.new('c', cd); scn.collection.objects.link(cam); scn.camera = cam
cd.type = 'ORTHO'; cd.ortho_scale = 6; scn.render.resolution_x, scn.render.resolution_y = 900, 600
os.makedirs(out, exist_ok=True)
for name, loc, rot in (('plus_x', (12, 0, 0), (math.pi/2, 0, math.pi/2)), ('minus_y', (0, -12, 0), (math.pi/2, 0, 0)), ('top', (0, 0, 12), (0, 0, 0))):
    cam.location = loc; cam.rotation_euler = rot
    scn.render.filepath = os.path.join(out, 'orient_' + name + '.png'); bpy.ops.render.render(write_still=True)
