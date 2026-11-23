"""Inspect a candidate GLB (read-only): objects, face counts, materials, world bounding box. Usage:
   blender --background --python scripts/inspect_candidate.py -- <file.glb>"""
import sys, json, os
import bpy
from mathutils import Vector
path = sys.argv[sys.argv.index('--') + 1]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=path)
rows, pts = [], []
for o in bpy.data.objects:
    if o.type != 'MESH':
        continue
    wb = [o.matrix_world @ Vector(c) for c in o.bound_box]
    pts += wb
    rows.append({'name': o.name, 'faces': len(o.data.polygons), 'tris': sum(len(p.vertices) - 2 for p in o.data.polygons), 'mats': [m.name if m else None for m in o.data.materials][:4],
                 'size': [round(max(getattr(p, a) for p in wb) - min(getattr(p, a) for p in wb), 3) for a in 'xyz']})
mn = [min(getattr(p, a) for p in pts) for a in 'xyz']; mx = [max(getattr(p, a) for p in pts) for a in 'xyz']
rep = {'file': os.path.basename(path), 'size_kb': round(os.path.getsize(path) / 1024), 'meshes': len(rows), 'tris_total': sum(r['tris'] for r in rows),
       'bbox_min': [round(v, 3) for v in mn], 'bbox_max': [round(v, 3) for v in mx], 'bbox_size_xyz': [round(mx[i] - mn[i], 3) for i in range(3)],
       'materials': sorted({m.name for m in bpy.data.materials}), 'objects_by_size': sorted(rows, key=lambda r: -r['tris'])[:25],
       'empties': [o.name for o in bpy.data.objects if o.type == 'EMPTY'][:20]}
print('INSPECT', json.dumps(rep))
