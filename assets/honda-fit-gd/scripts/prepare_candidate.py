"""
Candidate model A (Sketchfab "2006 Honda Fit GD3", kusuma844, CC BY 4.0): import, ALIGN to the project convention and SCALE to the manual's length.
It is a uniform scale (no stretching): the model keeps its own proportions, which are then MEASURED against the official dimensions.
Convention: +Z up, car front toward -Y, origin on the ground at the centre of the body. The source GLB is not modified.
   blender --background --python scripts/prepare_candidate.py -- candidates_local/candidate_A_2006_honda_fit_gd3.glb out/candidate_A [debug]
"""
import sys, os, json, math
import bpy
from mathutils import Vector, Matrix

a = sys.argv[sys.argv.index('--') + 1:]
path, out = a[0], a[1]
debug = 'debug' in a
front = next((x.split('=')[1] for x in a if x.startswith('front=')), '-x')      # which axis of the imported model is the car's front (default: the A model, -X)
length_axis = 'x' if front.endswith('x') else 'y'
os.makedirs(out, exist_ok=True)
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=path)
meshes = [o for o in bpy.data.objects if o.type == 'MESH']
bpy.context.view_layer.update()
world = {o.name: o.matrix_world.copy() for o in meshes}          # keep the importer's own orientation (glTF Y-up -> Blender Z-up)
root = bpy.data.objects.new('CandidateRoot', None)
bpy.context.collection.objects.link(root)
for o in meshes:
    o.parent = None
    o.matrix_world = world[o.name]
for e in [o for o in bpy.data.objects if o.type == 'EMPTY' and o is not root]:
    bpy.data.objects.remove(e, do_unlink=True)
bpy.context.view_layer.update()
for o in meshes:
    o.parent = root
    o.matrix_parent_inverse = Matrix.Identity(4)
    o.matrix_world = world[o.name]
bpy.context.view_layer.update()

def bbox():
    pts = [o.matrix_world @ Vector(c) for o in meshes for c in o.bound_box]
    return [min(getattr(p, k) for p in pts) for k in 'xyz'], [max(getattr(p, k) for p in pts) for k in 'xyz']

# rotate: the model's front is -X; the project's front is -Y  => rotate +90 deg about Z (-X -> -Y)
root.rotation_euler = (0, 0, {'-x': math.pi / 2, '+x': -math.pi / 2, '-y': 0.0, '+y': math.pi}[front])
bpy.context.view_layer.update()
mn, mx = bbox()
length = mx[1] - mn[1]
s = 3.830 / length                                         # uniform scale to the manual's 3830 mm
root.scale = (s, s, s)
bpy.context.view_layer.update()
mn, mx = bbox()
root.location = (-(mn[0] + mx[0]) / 2 + root.location.x, -(mn[1] + mx[1]) / 2 + root.location.y, -mn[2] + root.location.z)
bpy.context.view_layer.update()
mn, mx = bbox()

# width of the body below the belt line (door mirrors excluded) and the tyres
low = []
for o in meshes:
    for v in o.data.vertices:
        p = o.matrix_world @ v.co
        if p.z < 0.85:
            low.append(p)
width_low = max(p.x for p in low) - min(p.x for p in low)
biggest = max(meshes, key=lambda o: len(o.data.polygons))
body_h = max((biggest.matrix_world @ v.co).z for v in biggest.data.vertices)
rep = {'uniform_scale_applied': round(s, 5), 'length_m': round(mx[1] - mn[1], 3), 'width_with_mirrors_m': round(mx[0] - mn[0], 3), 'width_below_belt_m': round(width_low, 3),
       'height_m': round(mx[2] - mn[2], 3), 'height_of_largest_part_m': round(body_h, 3), 'front_axis_in_source': front, 'official_m': {'L': 3.830, 'W': 1.675, 'H': 1.525},
       'deviation_mm_vs_official': {'width_below_belt': round((width_low - 1.675) * 1000), 'height': round(((mx[2] - mn[2]) - 1.525) * 1000), 'height_largest_part': round((body_h - 1.525) * 1000)}}
for o in meshes:
    rep.setdefault('parts', {})[o.name] = {'tris': len(o.data.polygons), 'z_range_m': [round(min((o.matrix_world @ Vector(c)).z for c in o.bound_box), 3), round(max((o.matrix_world @ Vector(c)).z for c in o.bound_box), 3)]}

# neutral grey: one grey per part, or one debug colour per material to identify the parts
palette_debug = [(0.9, 0.2, 0.2, 1), (0.2, 0.7, 0.2, 1), (0.2, 0.3, 0.9, 1), (0.9, 0.8, 0.1, 1), (0.8, 0.2, 0.8, 1)]
for i, o in enumerate(meshes):
    for m in o.data.materials:
        if m:
            n = m.name.lower()
            grey = 0.66 if 'carpaint' in n else 0.16 if 'black' in n else 0.26 if 'glass' in n else 0.12 if 'material_43' in n else 0.58 if 'material_56' in n else 0.5
            m.diffuse_color = palette_debug[i % 5] if debug else ((grey, grey, grey + 0.02, 1) if any(k in n for k in ('carpaint', 'black', 'glass', 'material_')) else (0.66, 0.66, 0.68, 1))
if not debug:
    json.dump(rep, open(os.path.join(out, 'candidate_measurements.json'), 'w'), indent=1)
print('PREP', json.dumps(rep))
bpy.ops.wm.save_as_mainfile(filepath=os.path.join(out, 'candidate_aligned%s.blend' % ('_debug' if debug else '')))
