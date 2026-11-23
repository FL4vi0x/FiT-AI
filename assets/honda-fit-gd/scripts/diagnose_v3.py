"""
Technical diagnosis of the v3 body (read-only on the .blend): mesh integrity, normals, topology density, flank flatness, the distance of the
projected patches (lamps, glass) to the body, and interpenetration. Run:
    blender --background out/v3/fit_gd_2005_lx_stage2_body_v3.blend --python scripts/diagnose_v3.py
"""
import json, math, os
import bmesh, bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

deps = bpy.context.evaluated_depsgraph_get()
def evaluated_bm(name):
    o = bpy.data.objects[name]
    ev = o.evaluated_get(deps)
    bm = bmesh.new()
    bm.from_mesh(ev.to_mesh())
    bm.transform(o.matrix_world)
    bm.normal_update()
    return bm

rep = {}
bm = evaluated_bm('Body')
tris = sum(len(f.verts) - 2 for f in bm.faces)
nonman = [e for e in bm.edges if len(e.link_faces) > 2]
boundary = [e for e in bm.edges if len(e.link_faces) == 1]
zero = [f for f in bm.faces if f.calc_area() < 1e-9]
def aspect(f):
    ls = [e.calc_length() for e in f.edges]
    return max(ls) / max(min(ls), 1e-9)
bad_aspect = [f for f in bm.faces if aspect(f) > 8]
rep['mesh'] = {'verts': len(bm.verts), 'faces': len(bm.faces), 'tris': tris, 'non_manifold_edges': len(nonman), 'boundary_edges': len(boundary),
               'zero_area_faces': len(zero), 'faces_aspect_gt_8': len(bad_aspect), 'signed_volume_m3': round(bm.calc_volume(signed=True), 4)}
# normals: outward test, the car is a closed solid
bvh = BVHTree.FromBMesh(bm)
inward = 0
for f in bm.faces:
    c = f.calc_center_median()
    hit = bvh.ray_cast(c + f.normal * 0.004, f.normal)           # leaving outwards along the normal: a closed outward-facing shell has nothing in front
    if hit[0] is not None and hit[3] > 0.0 and hit[3] < 0.5:
        inward += 1
rep['normals'] = {'faces_whose_outward_ray_hits_the_body_again': inward, 'note': 'nonzero can mean concavities (wheel arches, groove) as well as flipped normals'}

# topology density along the car: distinct station rows
ys = sorted({round(v.co.y, 4) for v in bm.verts if v.co.x >= -1e-6})
T_MID = None
front = min(v.co.y for v in bm.verts)
rows = [round(y - front, 4) for y in ys]
rep['stations'] = {'total_rows': len(rows), 'rows_in_first_5cm': sum(1 for r in rows if r <= 0.05), 'rows_5cm_to_50cm': sum(1 for r in rows if 0.05 < r <= 0.5),
                   'rows_50cm_to_100cm': sum(1 for r in rows if 0.5 < r <= 1.0), 'mean_row_spacing_mid_body_m': round(sum(rows[i+1]-rows[i] for i in range(len(rows)) if 1.0 < rows[i] < 3.0) / max(1, sum(1 for r in rows if 1.0 < r < 3.0)), 4)}

# dihedral angles: where are the crease edges (and are they on the real character lines?)
big = [e for e in bm.edges if len(e.link_faces) == 2 and e.calc_face_angle(0) > math.radians(35)]
rep['creases'] = {'edges_over_35deg': len(big), 'share_of_edges_pct': round(100 * len(big) / len(bm.edges), 2)}

# flank flatness: normal variation over the side wall between the axles
import statistics
samples = []
for f in bm.faces:
    c = f.calc_center_median()
    t = c.y - front
    if 1.0 < t < 3.0 and c.x > 0.3 and 0.35 < c.z < 0.9 and abs(f.normal.x) > 0.6:
        samples.append(f.normal.copy())
if samples:
    mean = sum(samples, Vector()) / len(samples); mean.normalize()
    ang = [math.degrees(s.angle(mean)) for s in samples]
    rep['flank'] = {'faces': len(samples), 'normal_angle_std_deg': round(statistics.pstdev(ang), 2), 'normal_angle_max_deg': round(max(ang), 2)}

# patches (lamps / grille / glass): distance to the body and open boundaries
out = {}
bvh_body = BVHTree.FromBMesh(bm)
for name in [o.name for o in bpy.data.objects if o.type == 'MESH' and o.name not in ('Body', 'Ground') and 'Wheel' not in o.name]:
    pb = evaluated_bm(name)
    d = []
    for v in pb.verts:
        loc, n, i, dist = bvh_body.find_nearest(v.co)
        d.append(dist if loc is not None else 99)
    bnd = sum(1 for e in pb.edges if len(e.link_faces) == 1)
    out[name] = {'verts': len(pb.verts), 'open_boundary_edges': bnd, 'dist_to_body_mm_min_mean_max': [round(min(d)*1000,1), round(sum(d)/len(d)*1000,1), round(max(d)*1000,1)]}
    pb.free()
rep['patches'] = out

# interpenetration: tyres vs body
ov = {}
for w in [o.name for o in bpy.data.objects if o.name.endswith('Wheel')]:
    wb = evaluated_bm(w)
    wb_bvh = BVHTree.FromBMesh(wb)
    ov[w] = len(bvh_body.overlap(wb_bvh))
    wb.free()
rep['tyre_body_overlapping_triangle_pairs'] = ov
print('DIAG', json.dumps(rep))
json.dump(rep, open(os.path.join(os.path.dirname(bpy.data.filepath), 'diagnosis_v3.json'), 'w'), indent=1)
