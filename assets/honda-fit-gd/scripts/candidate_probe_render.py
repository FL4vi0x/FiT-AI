import sys, os, math
import bpy
from mathutils import Vector, Matrix
path = sys.argv[sys.argv.index('--') + 1]; out = sys.argv[sys.argv.index('--') + 2]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=path)
scn = bpy.context.scene
scn.render.engine = 'BLENDER_WORKBENCH'; scn.view_settings.view_transform = 'Standard'
sh = scn.display.shading; sh.light = 'STUDIO'; sh.color_type = 'OBJECT'; sh.show_object_outline = False
w = bpy.data.worlds.new('W'); w.color = (0.8, 0.8, 0.82); scn.world = w
cam_d = bpy.data.cameras.new('c'); cam = bpy.data.objects.new('c', cam_d); scn.collection.objects.link(cam); scn.camera = cam
cam_d.type = 'ORTHO'; cam_d.ortho_scale = 8
scn.render.resolution_x, scn.render.resolution_y = 1000, 700
for name, loc, rot in (('top', (-1.5, 0, 12), (0, 0, 0)), ('side_x', (-1.5, -12, 1.0), (math.pi/2, 0, 0)), ('front_y', (12, 0, 1.0), (math.pi/2, 0, math.pi/2))):
    cam.location = loc; cam.rotation_euler = rot
    scn.render.filepath = os.path.join(out, 'probe_' + name + '.png'); bpy.ops.render.render(write_still=True)
