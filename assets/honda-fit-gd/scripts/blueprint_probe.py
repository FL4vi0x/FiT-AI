"""Probe the auxiliary blueprint (orthographic side/front/top/rear) and print each view's bounding box. Read-only on the reference."""
# folder with the (third-party, never versioned) reference pack: set FITGD_REFERENCES_DIR, or keep the pack next to the repository
import os as _os
_REFS = _os.environ.get('FITGD_REFERENCES_DIR') or _os.path.abspath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..', '..', '..', '..', 'FIT_AI_Blender_Honda_Fit_2005_Pacote', 'FitAI_HondaFit2005_Modelagem', 'referencias'))

import numpy as np, sys
from PIL import Image
REF = _os.path.join(_REFS, 'uvUtO48dKKMlhzPc-yfK6IfipxxUXOmHo3V-ZSPNZ8YzTj0LupsxjhvKuonfs_6mLM-JpTTaxoSKongrxjg1KM7CWbq08WreoEOl0YxOjKSoJRJP5I8_dcOY2JsxFswN8kr1X4M1QtntvQm894QBWFuhBGUuyZQd9tMlVeTh2OsGQ05rwlxLT7wvv2k_Q3bO.jpg')
im = np.array(Image.open(REF).convert('L')).astype(float)
print(im.shape)
dark = im < 175
# column / row occupancy to find the gaps between views
cols = dark.sum(0); rows = dark.sum(1)
def runs(a, thr=3):
    on = a > thr; out=[]; s=None
    for i,v in enumerate(on):
        if v and s is None: s=i
        if not v and s is not None: out.append((s,i-1)); s=None
    if s is not None: out.append((s,len(a)-1))
    return out
print('col runs', runs(cols)[:12])
print('row runs', runs(rows)[:12])
# per quadrant bounding boxes
def bbox(x0,x1,y0,y1):
    sub = dark[y0:y1, x0:x1]
    ys,xs = np.nonzero(sub)
    return (x0+xs.min(), x0+xs.max(), y0+ys.min(), y0+ys.max())
for name,(x0,x1,y0,y1) in {'side':(0,925,0,392),'front':(925,1394,0,392),'top':(0,925,395,839),'rear':(925,1394,395,839)}.items():
    print(name, bbox(x0,x1,y0,y1))

print('--- side top profile (x, y of first dark px from top), every 25 px')
for x in range(5, 912, 25):
    col = dark[0:380, x]; ys = np.nonzero(col)[0]
    print(x, ys.min() if len(ys) else None, end=' | ')
print()
print('--- side lowest dark px per column (body+wheels), every 25 px, y<378')
for x in range(5, 912, 25):
    col = dark[0:378, x]; ys = np.nonzero(col)[0]
    print(x, ys.max() if len(ys) else None, end=' | ')
print()
print('--- top view: first/last dark row per column, every 25 px (plan half-width source)')
for x in range(7, 912, 25):
    col = dark[395:839, x]; ys = np.nonzero(col)[0]
    print(x, (395+ys.min(), 395+ys.max()) if len(ys) else None, end=' | ')
print()
print('--- front view (x 929-1386): first dark row per column every 20 px; and silhouette width per row')
for x in range(929, 1387, 20):
    col = dark[0:380, x]; ys = np.nonzero(col)[0]
    print(x, ys.min() if len(ys) else None, end=' | ')
print()
for y in range(10, 380, 20):
    r = dark[y, 929:1387]; xs = np.nonzero(r)[0]
    print(y, (929+xs.min(), 929+xs.max()) if len(xs) else None, end=' | ')
