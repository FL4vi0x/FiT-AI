"""List the parts of the aligned candidate (normalised metres: +Y rear? see prepare_candidate): name, material, triangles, bounding box and
how much of the car's outer shell each part could be (distance of its centre from the body's outer hull in the horizontal plane)."""
import sys, json
import bpy
from mathutils import Vector
rows = []
for o in bpy.data.objects:
    if o.type != 'MESH':
        continue
    pts = [o.matrix_world @ Vector(c) for c in o.bound_box]
    mn = [min(getattr(p, a) for p in pts) for a in 'xyz']; mx = [max(getattr(p, a) for p in pts) for a in 'xyz']
    rows.append({'name': o.name, 'mat': o.data.materials[0].name if o.data.materials else None, 'tris': len(o.data.polygons),
                 'x': [round(mn[0], 2), round(mx[0], 2)], 'y': [round(mn[1], 2), round(mx[1], 2)], 'z': [round(mn[2], 2), round(mx[2], 2)]})
rows.sort(key=lambda r: -r['tris'])
print('PARTS')
for r in rows:
    print(f"{r['name'][:34]:34} {str(r['mat'])[:14]:14} {r['tris']:5d}  x{r['x']} y{r['y']} z{r['z']}")
